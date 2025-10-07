# -*- coding: utf-8 -*-

##########################################################################
# OpenWebif: AjaxController
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

from Tools.Directories import fileExists
from Components.config import config
from time import mktime, localtime
from six import ensure_str
import os
import socket
import subprocess
import time
from datetime import datetime, timedelta

from Plugins.Extensions.OpenWebif.controllers.models.services import getBouquets, getChannels, getAllServices, getSatellites, getProviders, getEventDesc, getSimilarEpg, getChannelEpg, getSearchEpg, getCurrentFullInfo, getMultiEpg, getEvent
from Plugins.Extensions.OpenWebif.controllers.models.info import getInfo
from Plugins.Extensions.OpenWebif.controllers.models.movies import getMovieList, getMovieSearchList, getMovieInfo
from Plugins.Extensions.OpenWebif.controllers.models.timers import getTimers
from Plugins.Extensions.OpenWebif.controllers.models.config import getConfigs, getConfigsSections
from Plugins.Extensions.OpenWebif.controllers.models.stream import GetSession
from Plugins.Extensions.OpenWebif.controllers.base import BaseController
from Plugins.Extensions.OpenWebif.controllers.models.locations import getLocations
from Plugins.Extensions.OpenWebif.controllers.defaults import OPENWEBIFVER, getPublicPath, VIEWS_PATH, TRANSCODING, EXT_EVENT_INFO_SOURCE, HASAUTOTIMER, HASAUTOTIMERTEST, HASAUTOTIMERCHANGE, HASVPS, HASSERIES, ATSEARCHTYPES
from Plugins.Extensions.OpenWebif.controllers.utilities import getUrlArg, getEventInfoProvider
from Plugins.Extensions.OpenWebif import bruteforce_protection

try:
	from boxbranding import getBoxType, getMachineName, getMachineBrand, getMachineBuild
except:  # nosec # noqa: E722
	from Plugins.Extensions.OpenWebif.controllers.models.owibranding import getBoxType, getMachineName, getMachineBrand, getMachineBuild  # noqa: F401


class AjaxController(BaseController):
	"""
	Ajax Web Controller
	"""

	def __init__(self, session, path=""):
		BaseController.__init__(self, path=path, session=session)

	def NoDataRender(self):
		"""
		ajax requests with no extra data
		"""
		return ['powerstate', 'message', 'myepg', 'radio', 'terminal', 'bqe', 'tv', 'satfinder']

	def P_edittimer(self, request):
		pipzap = getInfo()['timerpipzap']
		autoadjust = getInfo()['timerautoadjust']
		return {"autoadjust": autoadjust, "pipzap": pipzap}

	def P_current(self, request):
		return getCurrentFullInfo(self.session)

	def P_bouquets(self, request):
		stype = getUrlArg(request, "stype", "tv")
		bouq = getBouquets(stype)
		return {"bouquets": bouq['bouquets'], "stype": stype}

	def P_providers(self, request):
		stype = getUrlArg(request, "stype", "tv")
		prov = getProviders(stype)
		return {"providers": prov['providers'], "stype": stype}

	def P_satellites(self, request):
		stype = getUrlArg(request, "stype", "tv")
		sat = getSatellites(stype)
		return {"satellites": sat['satellites'], "stype": stype}

	# http://enigma2/ajax/channels?id=1%3A7%3A1%3A0%3A0%3A0%3A0%3A0%3A0%3A0%3AFROM%20BOUQUET%20%22userbouquet.favourites.tv%22%20ORDER%20BY%20bouquet&stype=tv
	def P_channels(self, request):
		stype = getUrlArg(request, "stype", "tv")
		idbouquet = getUrlArg(request, "id", "ALL")
		channels = getChannels(idbouquet, stype)
		channels['transcoding'] = TRANSCODING
		channels['type'] = stype
		channels['showpicons'] = config.OpenWebif.webcache.showpicons.value
		channels['showpiconbackground'] = config.OpenWebif.responsive_show_picon_background.value
		channels['shownownextcolumns'] = config.OpenWebif.responsive_nownext_columns_enabled.value
		return channels

	# http://enigma2/ajax/eventdescription?idev=479&sref=1%3A0%3A19%3A1B1F%3A802%3A2%3A11A0000%3A0%3A0%3A0%3A
	def P_eventdescription(self, request):
		return getEventDesc(getUrlArg(request, "sref"), getUrlArg(request, "idev"))

	# http://enigma2/ajax/event?idev=479&sref=1%3A0%3A19%3A1B1F%3A802%3A2%3A11A0000%3A0%3A0%3A0%3A
	def P_event(self, request):
		event = getEvent(getUrlArg(request, "sref"), getUrlArg(request, "idev"))
		if event:
			# TODO: this shouldn't really be part of an event's data
			event['event']['recording_margin_before'] = config.recording.margin_before.value
			event['event']['recording_margin_after'] = config.recording.margin_after.value
			event['at'] = HASAUTOTIMER
			event['transcoding'] = TRANSCODING
			event['moviedb'] = config.OpenWebif.webcache.moviedb.value if config.OpenWebif.webcache.moviedb.value else EXT_EVENT_INFO_SOURCE
			event['extEventInfoProvider'] = extEventInfoProvider = getEventInfoProvider(event['moviedb'])
		return event

	def P_about(self, request):
		info = {}
		info["owiver"] = OPENWEBIFVER
		return {"info": info}

	def P_boxinfo(self, request):
		info = getInfo(self.session, need_fullinfo=True)
		type = getBoxType()

		if fileExists(getPublicPath("/images/boxes/" + type + ".png")):
			info["boximage"] = type + ".png"
		elif fileExists(getPublicPath("/images/boxes/" + type + ".jpg")):
			info["boximage"] = type + ".jpg"
		else:
			info["boximage"] = "unknown.png"
		return info

	# http://enigma2/ajax/epgpop?sstr=test&bouquetsonly=1
	def P_epgpop(self, request):
		events = []
		timers = []
		sref = getUrlArg(request, "sref")
		eventId = getUrlArg(request, "eventid")
		sstr = getUrlArg(request, "sstr")
		if sref is not None:
			if eventId is not None:
				ev = getSimilarEpg(sref, eventId)
			else:
				ev = getChannelEpg(sref)
			events = ev["events"]
		elif sstr is not None:
			fulldesc = False
			if getUrlArg(request, "full") != None:
				fulldesc = True
			bouquetsonly = False
			if getUrlArg(request, "bouquetsonly") != None:
				bouquetsonly = True
			ev = getSearchEpg(sstr, None, fulldesc, bouquetsonly)
			events = sorted(ev["events"], key=lambda ev: ev['begin_timestamp'])
		at = False
		if len(events) > 0:
			t = getTimers(self.session)
			timers = t["timers"]
			at = HASAUTOTIMER
		if config.OpenWebif.webcache.theme.value:
			theme = config.OpenWebif.webcache.theme.value
		else:
			theme = 'original'
		moviedb = config.OpenWebif.webcache.moviedb.value if config.OpenWebif.webcache.moviedb.value else EXT_EVENT_INFO_SOURCE
		extEventInfoProvider = getEventInfoProvider(moviedb)

		return {"theme": theme, "events": events, "timers": timers, "at": at, "moviedb": moviedb, "extEventInfoProvider": extEventInfoProvider}

	# http://enigma2/ajax/epgdialog?sstr=test&bouquetsonly=1
	def P_epgdialog(self, request):
		return self.P_epgpop(request)

	def P_screenshot(self, request):
		box = {}
		box['brand'] = "dmm"
		if getMachineBrand() == 'Vu+':
			box['brand'] = "vuplus"
		elif getMachineBrand() == 'GigaBlue':
			box['brand'] = "gigablue"
		elif getMachineBrand() == 'Edision':
			box['brand'] = "edision"
		elif getMachineBrand() == 'iQon':
			box['brand'] = "iqon"
		elif getMachineBrand() == 'Technomate':
			box['brand'] = "techomate"
		elif fileExists("/proc/stb/info/azmodel"):
			box['brand'] = "azbox"

		return {"box": box,
				"high_resolution": config.OpenWebif.webcache.screenshot_high_resolution.value,
				"refresh_auto": config.OpenWebif.webcache.screenshot_refresh_auto.value,
				"refresh_time": config.OpenWebif.webcache.screenshot_refresh_time.value
				}

	def P_movies(self, request):
		movies = getMovieList(request.args)
		movies['transcoding'] = TRANSCODING

		sorttype = config.OpenWebif.webcache.moviesort.value
		unsort = movies['movies']

		if sorttype == 'name':
			movies['movies'] = sorted(unsort, key=lambda k: k['eventname'])
		elif sorttype == 'named':
			movies['movies'] = sorted(unsort, key=lambda k: k['eventname'], reverse=True)
		elif sorttype == 'date':
			movies['movies'] = sorted(unsort, key=lambda k: k['recordingtime'])
		elif sorttype == 'dated':
			movies['movies'] = sorted(unsort, key=lambda k: k['recordingtime'], reverse=True)

		movies['sort'] = sorttype
		return movies

	def P_moviesearch(self, request):
		movies = getMovieSearchList(request.args)
		movies['transcoding'] = TRANSCODING

		sorttype = config.OpenWebif.webcache.moviesort.value
		unsort = movies['movies']

		if sorttype == 'name':
			movies['movies'] = sorted(unsort, key=lambda k: k['eventname'])
		elif sorttype == 'named':
			movies['movies'] = sorted(unsort, key=lambda k: k['eventname'], reverse=True)
		elif sorttype == 'date':
			movies['movies'] = sorted(unsort, key=lambda k: k['recordingtime'])
		elif sorttype == 'dated':
			movies['movies'] = sorted(unsort, key=lambda k: k['recordingtime'], reverse=True)

		movies['sort'] = sorttype
		return movies

	def P_timers(self, request):

		timers = getTimers(self.session)
		unsort = timers['timers']

		sorttype = getUrlArg(request, "sort")
		if sorttype == None:
			return timers

		if sorttype == 'name':
			timers['timers'] = sorted(unsort, key=lambda k: k['name'])
		elif sorttype == 'named':
			timers['timers'] = sorted(unsort, key=lambda k: k['name'], reverse=True)
		elif sorttype == 'date':
			timers['timers'] = sorted(unsort, key=lambda k: k['begin'])
		else:
			timers['timers'] = sorted(unsort, key=lambda k: k['begin'], reverse=True)
			sorttype = 'dated'

		timers['sort'] = sorttype
		return timers

	# http://enigma2/ajax/tvradio
	# (`classic` interface only)
	def P_tvradio(self, request):
		epgmode = getUrlArg(request, "epgmode", "tv")
		if epgmode not in ["tv", "radio"]:
			epgmode = "tv"
		return {"epgmode": epgmode}

	def P_config(self, request):
		section = getUrlArg(request, "section", "usage")
		return getConfigs(section)

	def P_settings(self, request):
		ret = {
			"result": True
		}
		ret['configsections'] = getConfigsSections()['sections']
		if config.OpenWebif.webcache.theme.value:
			if os.path.exists(getPublicPath('themes')):
				ret['themes'] = config.OpenWebif.webcache.theme.choices
			else:
				ret['themes'] = ['original', 'clear']
			ret['theme'] = config.OpenWebif.webcache.theme.value
		else:
			ret['themes'] = []
			ret['theme'] = 'original'
		if config.OpenWebif.webcache.moviedb.value:
			ret['moviedbs'] = config.OpenWebif.webcache.moviedb.choices
			ret['moviedb'] = config.OpenWebif.webcache.moviedb.value
		else:
			ret['moviedbs'] = []
			ret['moviedb'] = EXT_EVENT_INFO_SOURCE
		ret['zapstream'] = config.OpenWebif.webcache.zapstream.value
		ret['showpicons'] = config.OpenWebif.webcache.showpicons.value
		ret['showchanneldetails'] = config.OpenWebif.webcache.showchanneldetails.value
		ret['showiptvchannelsinselection'] = config.OpenWebif.webcache.showiptvchannelsinselection.value
		ret['screenshotchannelname'] = config.OpenWebif.webcache.screenshotchannelname.value
		ret['showallpackages'] = config.OpenWebif.webcache.showallpackages.value
		ret['allowipkupload'] = config.OpenWebif.allow_upload_ipk.value
		ret['smallremotes'] = [(x, _('%s Style') % x.capitalize()) for x in config.OpenWebif.webcache.smallremote.choices]
		ret['smallremote'] = config.OpenWebif.webcache.smallremote.value
		loc = getLocations()
		ret['locations'] = loc['locations']
		if os.path.exists(VIEWS_PATH + "/responsive"):
			ret['responsivedesign'] = config.OpenWebif.responsive_enabled.value
		return ret

	# http://enigma2/ajax/multiepg
	def P_multiepg(self, request):
		epgmode = getUrlArg(request, "epgmode", "tv")
		if epgmode not in ["tv", "radio"]:
			epgmode = "tv"

		bouq = getBouquets(epgmode)
		bref = getUrlArg(request, "bref")
		if bref == None:
			bref = bouq['bouquets'][0][0]
		endtime = 1440
		begintime = -1
		day = 0
		week = 0
		wadd = 0
		_week = getUrlArg(request, "week")
		if _week != None:
			try:
				week = int(_week)
				wadd = week * 7
			except ValueError:
				pass
		_day = getUrlArg(request, "day")
		if _day != None:
			try:
				day = int(_day)
				if day > 0 or wadd > 0:
					now = localtime()
					begintime = int(mktime((now.tm_year, now.tm_mon, now.tm_mday + day + wadd, 0, 0, 0, -1, -1, -1)))
			except ValueError:
				pass
		mode = 1
		if config.OpenWebif.webcache.mepgmode.value:
			try:
				mode = int(config.OpenWebif.webcache.mepgmode.value)
			except ValueError:
				pass
		epg = getMultiEpg(self, bref, begintime, endtime, mode)
		epg['bouquets'] = bouq['bouquets']
		epg['bref'] = bref
		epg['day'] = day
		epg['week'] = week
		epg['mode'] = mode
		epg['epgmode'] = epgmode
		return epg

	def P_epgr(self, request):
		ret = {}
		ret['showiptvchannelsinselection'] = config.OpenWebif.webcache.showiptvchannelsinselection.value
		return ret

	def P_at(self, request):
		ret = {}
		ret['hasVPS'] = 1 if HASVPS else 0
		ret['hasSeriesPlugin'] = 1 if HASSERIES else 0
		ret['test'] = 1 if HASAUTOTIMERTEST else 0
		ret['hasChange'] = 1 if HASAUTOTIMERCHANGE else 0
		ret['autoadjust'] = getInfo()['timerautoadjust']
		ret['searchTypes'] = ATSEARCHTYPES

		if config.OpenWebif.autotimer_regex_searchtype.value:
			ret['searchTypes']['regex'] = 0

		loc = getLocations()
		ret['locations'] = loc['locations']
		ret['showiptvchannelsinselection'] = config.OpenWebif.webcache.showiptvchannelsinselection.value
		return ret

	def P_webtv(self, request):
		streaming_port = int(config.OpenWebif.streamport.value)
		if config.OpenWebif.auth_for_streaming.value:
			session = GetSession()
			if session.GetAuth(request) is not None:
				auth = ':'.join(session.GetAuth(request)) + "@"
			else:
				auth = '-sid:' + ensure_str(session.GetSID(request)) + "@"
		else:
			auth = ''
		vxgenabled = False
		if fileExists(getPublicPath("/vxg/media_player.pexe")):
			vxgenabled = True
		transcoding = TRANSCODING
		transcoder_port = 0
		if transcoding:
			try:
				transcoder_port = int(config.plugins.transcodingsetup.port.value)
				if getMachineBuild() in ('inihdp', 'hd2400', 'et10000', 'et13000', 'sf5008', 'ew7356', 'formuler1tc', 'tiviaraplus', '8100s'):
					transcoder_port = int(config.OpenWebif.streamport.value)
			except Exception:
				transcoder_port = 0
		return {"transcoder_port": transcoder_port, "vxgenabled": vxgenabled, "auth": auth, "streaming_port": streaming_port}

	def P_editmovie(self, request):
		sref = getUrlArg(request, "sRef")
		title = ""
		description = ""
		tags = ""
		resulttext = ""
		result = False
		if sref:
			mi = getMovieInfo(sref, NewFormat=True)
			result = mi["result"]
			if result:
				title = mi["title"]
				if title:
					description = mi["description"]
					tags = mi["tags"]
				else:
					result = False
					resulttext = "meta file not found"
			else:
				resulttext = mi["resulttext"]
		return {"title": title, "description": description, "sref": sref, "result": result, "tags": tags, "resulttext": resulttext}

	def P_epgplayground(self, request):
		TV = 'tv'
		RADIO = 'radio'

		ret = {
			'tvBouquets': getBouquets(TV),
			'tvChannels': getAllServices(TV),
			'radioBouquets': getBouquets(RADIO),
			'radioChannels': getAllServices(RADIO),
		}
		return {'data': ret}

	def _check_local_network(self, request):
		"""
		Check if request is from local network (172.58.x.x or 192.168.x.x or 10.x.x.x)
		Returns True if local, False otherwise
		"""
		client_ip = request.getClientAddress().host

		# Allow localhost
		if client_ip in ['127.0.0.1', '::1', 'localhost']:
			return True

		# Check for private network ranges
		if client_ip.startswith('192.168.') or \
		   client_ip.startswith('172.') or \
		   client_ip.startswith('10.') or \
		   client_ip.startswith('fe80::'):  # IPv6 link-local
			return True

		return False

	def P_status_dashboard(self, request):
		"""
		Render the status dashboard HTML page
		Only accessible from local network
		"""
		if not self._check_local_network(request):
			return {
				"result": False,
				"message": "Access denied: Dashboard only accessible from local network"
			}

		return {
			"result": True,
			"template": "ajax/status_dashboard.tmpl"
		}

	def P_status_dashboard_data(self, request):
		"""
		Provide JSON data for the status dashboard
		Only accessible from local network
		"""
		if not self._check_local_network(request):
			return {
				"result": False,
				"message": "Access denied: Dashboard only accessible from local network"
			}

		# Collect all data
		data = {
			"network": self._get_network_info(),
			"vpn": self._get_vpn_status(),
			"protection": self._get_protection_stats(),
			"system": self._get_system_info(),
			"attacks": self._get_attack_stats(),
			"locked_ips": self._get_locked_ips()
		}

		return data

	def _get_network_info(self):
		"""Get network information"""
		try:
			hostname = socket.gethostname()

			# Get main interface and IP
			interface = "unknown"
			local_ip = "unknown"
			gateway = "unknown"

			try:
				# Get default route interface
				route_output = subprocess.check_output(['ip', 'route', 'show', 'default'],
													   stderr=subprocess.STDOUT)
				if route_output:
					parts = route_output.decode('utf-8').strip().split()
					if 'dev' in parts:
						interface = parts[parts.index('dev') + 1]
					if 'via' in parts:
						gateway = parts[parts.index('via') + 1]
			except:
				pass

			try:
				# Get IP address of interface
				if interface != "unknown":
					ip_output = subprocess.check_output(['ip', 'addr', 'show', interface],
													    stderr=subprocess.STDOUT)
					lines = ip_output.decode('utf-8').split('\n')
					for line in lines:
						if 'inet ' in line:
							local_ip = line.strip().split()[1].split('/')[0]
							break
			except:
				pass

			# Try to get public IP (with timeout)
			public_ip = "Detecting..."
			try:
				# Quick check, 3 second timeout
				public_ip = subprocess.check_output(
					['wget', '-qO-', '--timeout=3', 'http://ipecho.net/plain'],
					stderr=subprocess.STDOUT,
					timeout=5
				).decode('utf-8').strip()
			except:
				try:
					public_ip = subprocess.check_output(
						['wget', '-qO-', '--timeout=3', 'http://ifconfig.me'],
						stderr=subprocess.STDOUT,
						timeout=5
					).decode('utf-8').strip()
				except:
					public_ip = "Unable to detect"

			return {
				"hostname": hostname,
				"local_ip": local_ip,
				"public_ip": public_ip,
				"interface": interface,
				"gateway": gateway
			}
		except Exception as e:
			print("[OpenWebif] Status dashboard: Error getting network info: %s" % str(e))
			return {
				"hostname": "unknown",
				"local_ip": "unknown",
				"public_ip": "unknown",
				"interface": "unknown",
				"gateway": "unknown"
			}

	def _get_vpn_status(self):
		"""Get WireGuard VPN status"""
		try:
			# Check if wg0 interface exists and get status
			wg_output = subprocess.check_output(['wg', 'show', 'wg0'],
											    stderr=subprocess.STDOUT)
			wg_text = wg_output.decode('utf-8')

			# Parse WireGuard output
			vpn_ip = "unknown"
			peers = 0
			last_handshake = "Never"

			# Get VPN IP
			try:
				ip_output = subprocess.check_output(['ip', 'addr', 'show', 'wg0'],
												    stderr=subprocess.STDOUT)
				lines = ip_output.decode('utf-8').split('\n')
				for line in lines:
					if 'inet ' in line:
						vpn_ip = line.strip().split()[1].split('/')[0]
						break
			except:
				pass

			# Count peers and get last handshake
			for line in wg_text.split('\n'):
				if line.startswith('peer:'):
					peers += 1
				if 'latest handshake:' in line:
					last_handshake = line.split('latest handshake:')[1].strip()

			return {
				"status": "online",
				"ip": vpn_ip,
				"peers": str(peers),
				"last_handshake": last_handshake
			}
		except subprocess.CalledProcessError:
			# WireGuard not running
			return {
				"status": "offline",
				"ip": "N/A",
				"peers": "0",
				"last_handshake": "N/A"
			}
		except Exception as e:
			print("[OpenWebif] Status dashboard: Error getting VPN status: %s" % str(e))
			return {
				"status": "error",
				"ip": "Error",
				"peers": "0",
				"last_handshake": "Error"
			}

	def _get_protection_stats(self):
		"""Get brute force protection statistics"""
		try:
			status = bruteforce_protection.get_status()

			# Count locked IPs
			locked_count = 0
			for ip_data in status.get('details', []):
				if ip_data.get('locked', False):
					locked_count += 1

			# Parse log file for additional stats
			total_failed = 0
			total_success = 0
			global_attacks = 0

			try:
				if os.path.exists(bruteforce_protection.LOG_FILE):
					with open(bruteforce_protection.LOG_FILE, 'r') as f:
						for line in f:
							if 'FAILED' in line:
								total_failed += 1
							if 'SUCCESS' in line:
								total_success += 1
							if 'GLOBAL ATTACK' in line:
								global_attacks += 1
			except:
				pass

			return {
				"tracked_ips": str(status.get('tracked_ips', 0)),
				"locked_ips": str(locked_count),
				"total_failed": str(total_failed),
				"total_success": str(total_success),
				"global_attacks": str(global_attacks)
			}
		except Exception as e:
			print("[OpenWebif] Status dashboard: Error getting protection stats: %s" % str(e))
			return {
				"tracked_ips": "0",
				"locked_ips": "0",
				"total_failed": "0",
				"total_success": "0",
				"global_attacks": "0"
			}

	def _get_system_info(self):
		"""Get system information"""
		try:
			# System name
			system_name = "TNAP 6 SF8008"
			try:
				with open('/etc/issue', 'r') as f:
					system_name = f.read().strip().split('\n')[0]
			except:
				pass

			# Kernel version
			kernel = "unknown"
			try:
				kernel = subprocess.check_output(['uname', '-r'],
											    stderr=subprocess.STDOUT).decode('utf-8').strip()
			except:
				pass

			# Uptime
			uptime_str = "unknown"
			try:
				with open('/proc/uptime', 'r') as f:
					uptime_seconds = float(f.read().split()[0])
					days = int(uptime_seconds // 86400)
					hours = int((uptime_seconds % 86400) // 3600)
					minutes = int((uptime_seconds % 3600) // 60)
					uptime_str = "%dd %dh %dm" % (days, hours, minutes)
			except:
				pass

			# Load average
			load_str = "unknown"
			try:
				with open('/proc/loadavg', 'r') as f:
					load_str = ' '.join(f.read().split()[:3])
			except:
				pass

			# Memory usage
			memory_str = "unknown"
			memory_percent = 0
			try:
				with open('/proc/meminfo', 'r') as f:
					meminfo = {}
					for line in f:
						parts = line.split(':')
						if len(parts) == 2:
							meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])

					total = meminfo.get('MemTotal', 0)
					free = meminfo.get('MemFree', 0) + meminfo.get('Buffers', 0) + meminfo.get('Cached', 0)
					used = total - free

					if total > 0:
						memory_percent = int((used * 100.0) / total)
						memory_str = "%d MB / %d MB (%d%%)" % (used // 1024, total // 1024, memory_percent)
			except:
				pass

			return {
				"name": system_name,
				"kernel": kernel,
				"uptime": uptime_str,
				"load": load_str,
				"memory": memory_str,
				"memory_percent": memory_percent
			}
		except Exception as e:
			print("[OpenWebif] Status dashboard: Error getting system info: %s" % str(e))
			return {
				"name": "unknown",
				"kernel": "unknown",
				"uptime": "unknown",
				"load": "unknown",
				"memory": "unknown",
				"memory_percent": 0
			}

	def _get_attack_stats(self):
		"""Get recent attack statistics from log file"""
		try:
			now = time.time()
			last_24h_count = 0
			last_1h_count = 0
			unique_ips = set()

			if os.path.exists(bruteforce_protection.LOG_FILE):
				with open(bruteforce_protection.LOG_FILE, 'r') as f:
					for line in f:
						if 'FAILED' not in line:
							continue

						# Parse timestamp
						try:
							timestamp_str = line.split('[')[1].split(']')[0]
							log_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
							log_timestamp = time.mktime(log_time.timetuple())

							# Count if within 24 hours
							if now - log_timestamp < 86400:
								last_24h_count += 1

								# Extract IP
								if 'IP ' in line:
									ip_part = line.split('IP ')[1].split()[0].rstrip(',')
									unique_ips.add(ip_part)

							# Count if within 1 hour
							if now - log_timestamp < 3600:
								last_1h_count += 1
						except:
							continue

			return {
				"last_24h": str(last_24h_count),
				"last_1h": str(last_1h_count),
				"unique_ips": str(len(unique_ips))
			}
		except Exception as e:
			print("[OpenWebif] Status dashboard: Error getting attack stats: %s" % str(e))
			return {
				"last_24h": "0",
				"last_1h": "0",
				"unique_ips": "0"
			}

	def _get_locked_ips(self):
		"""Get list of currently locked IPs"""
		try:
			status = bruteforce_protection.get_status()
			locked_list = []

			for ip_data in status.get('details', []):
				if ip_data.get('locked', False):
					locked_list.append({
						"ip": ip_data.get('ip', 'unknown'),
						"attempts": str(ip_data.get('attempts', 0)),
						"remaining": str(ip_data.get('lockout_remaining', 0))
					})

			return locked_list
		except Exception as e:
			print("[OpenWebif] Status dashboard: Error getting locked IPs: %s" % str(e))
			return []
