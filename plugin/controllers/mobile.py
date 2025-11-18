# -*- coding: utf-8 -*-

##########################################################################
# OpenWebif: MobileController
##########################################################################
# Copyright (C) 2011 - 2018 E2OpenPlugins
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

from six.moves.urllib.parse import quote
from time import localtime, strftime

from Plugins.Extensions.OpenWebif.controllers.base import BaseController
from Plugins.Extensions.OpenWebif.controllers.models.movies import getMovieList
from Plugins.Extensions.OpenWebif.controllers.models.timers import getTimers
from Plugins.Extensions.OpenWebif.controllers.models.services import getBouquets, getChannels, getChannelEpg, getEvent, getPicon
from Plugins.Extensions.OpenWebif.controllers.defaults import TRANSCODING
from Plugins.Extensions.OpenWebif.controllers.utilities import getUrlArg
from Components.config import config
from six import ensure_str


class MobileController(BaseController):
	"""
	Mobile Web Controller
	"""

	def __init__(self, session, path=""):
		BaseController.__init__(self, path=path, session=session, isMobile=True)

	def NoDataRender(self):
		"""
		mobile requests with no extra data
		"""
		return ['index', 'control', 'screenshot', 'satfinder', 'about']

	def P_bouquets(self, request):
		stype = getUrlArg(request, "stype", "tv")
		return getBouquets(stype)

	def P_channels(self, request):
		stype = getUrlArg(request, "stype", "tv")
		idbouquet = getUrlArg(request, "id", "ALL")
		channels = getChannels(idbouquet, stype)
		channels['transcoding'] = TRANSCODING
		return channels

	def P_channelinfo(self, request):
		channelinfo = {}
		channelepg = {}
		sref = getUrlArg(request, "sref")
		if sref != None:
			channelepg = getChannelEpg(sref)
			# Detect if sRef contains a stream
			if ("://" in sref):
				# Repair sRef (URL part gets unquoted somewhere in between but MUST NOT)
				sref = ":".join(sref.split(':')[:10]) + ":" + quote(":".join(sref.split(':')[10:-1])) + ":" + sref.split(':')[-1]
				# Get service name from last part of the sRef
				channelinfo['sname'] = sref.split(':')[-1]
				# Use quoted sref when stream has EPG
				if len(channelepg['events']) > 1:
					channelepg['events'][0]['sref'] = sref
			else:
				# todo: Get service name
				channelinfo['sname'] = ""
			# Assume some sane blank defaults
			channelinfo['sref'] = sref
			channelinfo['title'] = ""
			channelinfo['picon'] = ""
			channelinfo['shortdesc'] = ""
			channelinfo['longdesc'] = ""
			channelinfo['begin'] = 0
			channelinfo['end'] = 0

		# Got EPG information?
		if len(channelepg['events']) > 1:
			# Return the EPG
			return {"channelinfo": channelepg["events"][0], "channelepg": channelepg["events"]}
		else:
			# Make sure at least some basic channel info gets returned when there is no EPG
			return {"channelinfo": channelinfo, "channelepg": None}

	def P_eventview(self, request):
		event = {}
		event['sref'] = ""
		event['title'] = ""
		event['picon'] = ""
		event['shortdesc'] = ""
		event['longdesc'] = ""
		event['begin'] = 0
		event['end'] = 0
		event['duration'] = 0
		event['channel'] = ""

		eventid = getUrlArg(request, "eventid")
		ref = getUrlArg(request, "eventref")
		if ref and eventid:
			event = getEvent(ref, eventid)['event']
			event['id'] = eventid
			event['picon'] = getPicon(ref)
			event['end'] = event['begin'] + event['duration']
			event['duration'] = int(event['duration'] / 60)
			event['start'] = event['begin']
			event['begin'] = strftime("%H:%M", (localtime(event['begin'])))
			event['end'] = strftime("%H:%M", (localtime(event['end'])))

		return {"event": event}

	def P_timerlist(self, request):
		return getTimers(self.session)

	def P_movies(self, request):
		movies = getMovieList(request.args)
		movies['transcoding'] = TRANSCODING
		return movies

	def P_remote(self, request):
		try:
			from Components.RcModel import rc_model
			REMOTE = rc_model.getRcFolder() + "/remote"
		except:
			from Plugins.Extensions.OpenWebif.controllers.models.owibranding import rc_model
			REMOTE = rc_model().getRcFolder()
		return {"remote": REMOTE}

	def P_videoplayer(self, request):
		"""
		HTML5 video player for mobile browsers
		"""
		from six.moves.urllib.parse import unquote
		from Plugins.Extensions.OpenWebif.controllers.models.stream import GetSession
		from Plugins.Extensions.OpenWebif.controllers.models.info import getInfo
		import os

		sRef = getUrlArg(request, "ref")
		if sRef:
			sRef = unquote(unquote(sRef))
		else:
			sRef = ""

		name = getUrlArg(request, "name", "Stream")

		# Build stream URL
		portNumber = config.OpenWebif.streamport.value
		transcoder_port = None
		args = ""
		transcoding_enabled = False

		# Get image info for URL parameter format
		info = getInfo()
		urlparam = '?'
		if info["imagedistro"] in ('openpli', 'satdreamgr', 'openvision'):
			urlparam = '&'

		# Check for transcoding
		device = getUrlArg(request, "device")

		try:
			from Tools.Directories import fileExists
			# Broadcom hardware encoder
			if fileExists("/dev/bcm_enc0"):
				try:
					transcoder_port = int(config.plugins.transcodingsetup.port.value)
				except Exception:
					transcoder_port = None
				if device == "phone" and transcoder_port:
					portNumber = transcoder_port
					transcoding_enabled = True
			# HiSilicon/encoder0 hardware encoders (SF8008, etc)
			elif fileExists("/dev/encoder0") or fileExists("/proc/stb/encoder/0/apply"):
				transcoder_port = portNumber
				if device == "phone":
					# Activate hardware encoder via proc interface
					try:
						# Get transcoding settings from config
						bitrate = str(config.plugins.transcodingsetup.bitrate.value)
						width = str(config.plugins.transcodingsetup.width.value)
						height = str(config.plugins.transcodingsetup.height.value)
						aspectratio = str(config.plugins.transcodingsetup.aspectratio.value)
						vcodec = str(config.plugins.transcodingsetup.video_codec.value)
						acodec = str(config.plugins.transcodingsetup.audio_codec.value)

						# Apply settings to hardware encoder
						encoder_base = "/proc/stb/encoder/0/"
						if os.path.exists(encoder_base + "bitrate"):
							open(encoder_base + "bitrate", "w").write(bitrate)
						if os.path.exists(encoder_base + "width"):
							open(encoder_base + "width", "w").write(width)
						if os.path.exists(encoder_base + "height"):
							open(encoder_base + "height", "w").write(height)
						if os.path.exists(encoder_base + "aspectratio"):
							open(encoder_base + "aspectratio", "w").write(aspectratio)
						if os.path.exists(encoder_base + "vcodec"):
							open(encoder_base + "vcodec", "w").write(vcodec)
						if os.path.exists(encoder_base + "acodec"):
							open(encoder_base + "acodec", "w").write(acodec)
						# Activate encoder
						if os.path.exists(encoder_base + "apply"):
							open(encoder_base + "apply", "w").write("1")

						transcoding_enabled = True
					except Exception as e:
						print("[OpenWebif] Failed to activate encoder:", str(e))
						pass
		except:
			pass

		# Authentication
		if config.OpenWebif.auth_for_streaming.value:
			asession = GetSession()
			if asession.GetAuth(request) is not None:
				auth = ':'.join(asession.GetAuth(request)) + "@"
			else:
				auth = '-sid:' + ensure_str(asession.GetSID(request)) + "@"
		else:
			auth = ''

		streamurl = "http://%s%s:%s/%s%s" % (auth, request.getRequestHostname(), portNumber, sRef, args)

		return {
			"streamurl": streamurl,
			"name": name,
			"transcoding": transcoding_enabled
		}
