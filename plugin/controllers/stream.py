# -*- coding: utf-8 -*-

##########################################################################
# OpenWebif: StreamAdapter, StreamController
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

from twisted.web import resource, server
from twisted.internet import reactor
from Components.Converter.Streaming import Streaming
from Components.Sources.StreamService import StreamService
from Plugins.Extensions.OpenWebif.controllers.utilities import PY3
import weakref

streamList = []
streamStates = []

MAX_CONCURRENT_STREAMS = 10
STREAM_TIMEOUT = 300


class StreamAdapter:
	EV_BEGIN = 0
	EV_STOP = 1

	def __init__(self, session, request):
		self.nav = session.nav
		self.request = request
		self.converter = None
		self.timeout_call = None
		self._closed = False

		self.mystream = StreamService(self.nav)
		if PY3:
			self.mystream.handleCommand(request.args[b"StreamService"][0].decode(encoding='utf-8', errors='strict'))
		else:
			self.mystream.handleCommand(request.args["StreamService"][0])
		self.mystream.execBegin()
		self.service = self.mystream.getService()
		self.nav.record_event.append(self.requestWrite)
		request.notifyFinish().addCallback(self.close, None)
		request.notifyFinish().addErrback(self.close, None)
		self.mystream.clientIP = request.getAllHeaders().get('x-forwarded-for', request.getClientIP())
		self.mystream.streamIndex = len(streamList)
		self.mystream.request = weakref.ref(request)
		streamList.append(self.mystream)
		self.setStatus(StreamAdapter.EV_BEGIN)

		self.timeout_call = reactor.callLater(STREAM_TIMEOUT, self.timeout)

	def timeout(self):
		if not self._closed:
			try:
				req = self.mystream.request()
				if req:
					req.finish()
			except:
				pass
			self.close()

	def setStatus(self, state):
		for x in streamStates:
			try:
				x(state, self.mystream)
			except:
				pass

	def close(self, nothandled1=None, nothandled2=None):
		if self._closed:
			return
		self._closed = True

		if self.timeout_call and self.timeout_call.active():
			self.timeout_call.cancel()

		try:
			self.mystream.execEnd()
		except:
			pass

		try:
			self.nav.record_event.remove(self.requestWrite)
		except:
			pass

		if self.converter is not None:
			try:
				self.converter.source = None
			except:
				pass
			self.converter = None

		if self.mystream in streamList:
			streamList.remove(self.mystream)

		self.mystream.request = None
		self.request = None

		self.setStatus(StreamAdapter.EV_STOP)

	def requestWrite(self, notused1=None, notused2=None):
		if self._closed:
			return

		try:
			req = self.mystream.request() if hasattr(self.mystream.request, '__call__') else self.mystream.request
			if not req:
				return

			if self.converter is None:
				converter_args = []
				self.converter = Streaming(converter_args)
				self.converter.source = self

			text = self.converter.getText()
			if PY3:
				req.write(text.encode(encoding='utf-8', errors='strict'))
			else:
				req.write(text)
		except:
			self.close()


class StreamController(resource.Resource):
	def __init__(self, session, path=""):
		resource.Resource.__init__(self)
		self.session = session

	def render(self, request):
		StreamAdapter(self.session, request)
		return server.NOT_DONE_YET
