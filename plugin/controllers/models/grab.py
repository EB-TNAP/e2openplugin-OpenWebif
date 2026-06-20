# -*- coding: utf-8 -*-

##########################################################################
# OpenWebif: grab
##########################################################################
# Copyright (C) 2011 - 2020 E2OpenPlugins
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston MA 02110-1301, USA.
##########################################################################

from __future__ import print_function
from enigma import eConsoleAppContainer
from ServiceReference import ServiceReference
from Components.config import config
from Screens.InfoBar import InfoBar
from twisted.web import resource, server
from twisted.internet import reactor
from enigma import eDBoxLCD
import time
from Plugins.Extensions.OpenWebif.controllers.utilities import getUrlArg

GRAB_PATH = '/usr/bin/grab'

# When no live service is playing (e.g. during blindscan) we fall back to
# OSD-only mode.  The new screen may not have finished its first render cycle
# by the time the grab request arrives, so we delay execution slightly to let
# enigma2 complete the paint before capturing.
OSD_FALLBACK_GRAB_DELAY = 0.75


class GrabRequest(object):
	def __init__(self, request, session):
		self.request = request
		self._delay_timer = None

		mode = None
		graboptions = [GRAB_PATH, '-q', '-s']

		fileformat = getUrlArg(request, "format", "jpg")
		if fileformat == "jpg":
			graboptions.append("-j")
			graboptions.append("95")
		elif fileformat == "png":
			graboptions.append("-p")
		elif fileformat != "bmp":
			fileformat = "bmp"

		size = getUrlArg(request, "r")

		mode = getUrlArg(request, "mode")
		# When no live service is playing (e.g. tuner taken over during blindscan)
		# and the caller has not explicitly requested a specific capture layer,
		# fall back to OSD-only mode so overlay dialogs are captured cleanly
		# without video bleed-through from the framebuffer background.
		osd_fallback = False
		if mode is None or mode not in ("osd", "video", "pip", "lcd"):
			try:
				if session.nav.getCurrentlyPlayingServiceReference() is None:
					mode = "osd"
					osd_fallback = True
			except Exception:
				mode = "osd"
				osd_fallback = True

		# OSD-only capture reads the raw framebuffer in software; on 4K boxes
		# this can be very slow.  Cap to 1280px when the caller did not request
		# a specific size so the grab completes quickly without sacrificing
		# readability of dialog screens.
		if osd_fallback and size is None:
			size = "1280"

		if size != None:
			graboptions.append("-r")
			graboptions.append("%d" % int(size))

		command = None
		if mode != None:
			if mode == "osd":
				graboptions.append("-o")
			elif mode == "video":
				graboptions.append("-v")
			elif mode == "pip":
				graboptions.append("-v")
				if InfoBar.instance.session.pipshown:
					graboptions.append("-i 1")
			elif mode == "lcd":
				eDBoxLCD.getInstance().dumpLCD()
				fileformat = "png"
				command = "cat /tmp/lcdshot.%s" % fileformat

		self._mode = mode
		self._command = command
		self._graboptions = graboptions

		self.filepath = "/tmp/screenshot." + fileformat
		self.container = eConsoleAppContainer()
		self.container.appClosed.append(self.grabFinished)
		self.container.stdoutAvail.append(request.write)
		self.container.setBufferSize(32768)

		try:
			if mode == "pip" and InfoBar.instance.session.pipshown:
				ref = InfoBar.instance.session.pip.getCurrentService().toString()
			else:
				ref = session.nav.getCurrentlyPlayingServiceReference().toString()
			sref = '_'.join(ref.split(':', 10)[:10])
			if config.OpenWebif.webcache.screenshotchannelname.value:
				sref = ServiceReference(ref).getServiceName()
		except:  # nosec # noqa: E722
			sref = 'screenshot'

		sref = sref + '_' + time.strftime("%Y%m%d%H%M%S", time.localtime(time.time()))
		request.notifyFinish().addErrback(self.requestAborted)
		request.setHeader('Content-Disposition', 'inline; filename=%s.%s;' % (sref, fileformat))
		request.setHeader('Content-Type', 'image/%s' % fileformat.replace("jpg", "jpeg"))
		request.setHeader('Expires', 'Sat, 26 Jul 1997 05:00:00 GMT')
		request.setHeader('Cache-Control', 'no-store, must-revalidate, post-check=0, pre-check=0')
		request.setHeader('Pragma', 'no-cache')

		if osd_fallback:
			self._delay_timer = reactor.callLater(OSD_FALLBACK_GRAB_DELAY, self._executeGrab)
		else:
			self._executeGrab()

	def _executeGrab(self):
		self._delay_timer = None
		if self._mode == "lcd":
			if self.container.execute(self._command):
				raise Exception("failed to execute: ", self._command)
		else:
			self.container.execute(GRAB_PATH, *self._graboptions)

	def requestAborted(self, err):
		# Called when client disconnected early; cancel any pending timer,
		# abort the process and don't call request.finish().
		if self._delay_timer is not None:
			try:
				self._delay_timer.cancel()
			except Exception:
				pass
			self._delay_timer = None
		else:
			del self.container.appClosed[:]
			self.container.kill()
		del self.request
		del self.container

	def grabFinished(self, retval=None):
		try:
			self.request.finish()
		except RuntimeError as error:
			print("[OpenWebif] grabFinished error: %s" % error)
		# Break the chain of ownership
		del self.request


class grabScreenshot(resource.Resource):
	def __init__(self, session, path=None):
		resource.Resource.__init__(self)
		self.session = session

	def render(self, request):
		# Add a reference to the grabber to the Request object. This keeps
		# the object alive at least until the request finishes
		request.grab_in_progress = GrabRequest(request, self.session)
		return server.NOT_DONE_YET
