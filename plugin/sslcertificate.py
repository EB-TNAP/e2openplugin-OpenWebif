# -*- coding: utf-8 -*-

##########################################################################
# OpenWebif: sslcertificate
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

from Tools.Directories import resolveFilename, SCOPE_CONFIG

import datetime
import ipaddress
import os
import socket

CA_FILE = resolveFilename(SCOPE_CONFIG, "ca.pem")
KEY_FILE = resolveFilename(SCOPE_CONFIG, "key.pem")
CERT_FILE = resolveFilename(SCOPE_CONFIG, "cert.pem")
CHAIN_FILE = resolveFilename(SCOPE_CONFIG, "chain.pem")


class SSLCertificateGenerator:

	def __init__(self):
		self.bits = 2048

	def _certNeedsRegen(self):
		# Regenerate if cert is v1 (no SANs) - modern browsers reject these
		try:
			from OpenSSL import crypto
			cert = crypto.load_certificate(crypto.FILETYPE_PEM, open(CERT_FILE, 'rt').read())
			if cert.get_version() < 2:
				print("[OpenWebif] Existing cert is v1 (no SANs), regenerating...")
				return True
			for i in range(cert.get_extension_count()):
				if cert.get_extension(i).get_short_name() == b'subjectAltName':
					return False
			print("[OpenWebif] Existing cert has no SANs, regenerating...")
			return True
		except Exception:
			return True

	def _getLocalIPs(self):
		ips = []
		try:
			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect(('8.8.8.8', 80))
			ips.append(s.getsockname()[0])
			s.close()
		except Exception:
			pass
		return ips

	# generate and install a self signed SSL certificate if none exists
	def installCertificates(self):
		if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
			if not self._certNeedsRegen():
				return
			os.remove(CERT_FILE)
			os.remove(KEY_FILE)
		key_pem, cert_pem = self._genKeyAndCert()
		print("[OpenWebif] Install newly generated key pair and certificate")
		open(KEY_FILE, "wt").write(key_pem)
		open(CERT_FILE, "wt").write(cert_pem)

	def _genKeyAndCert(self):
		from cryptography import x509
		from cryptography.x509.oid import NameOID
		from cryptography.hazmat.primitives import hashes, serialization
		from cryptography.hazmat.primitives.asymmetric import rsa
		from cryptography.hazmat.backends import default_backend

		hostname = socket.gethostname()
		now = datetime.datetime.utcnow()

		key = rsa.generate_private_key(
			public_exponent=65537,
			key_size=self.bits,
			backend=default_backend()
		)

		subject = x509.Name([
			x509.NameAttribute(NameOID.ORGANIZATION_NAME, u'Home'),
			x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, hostname),
			x509.NameAttribute(NameOID.COMMON_NAME, hostname),
		])

		san_names = [
			x509.DNSName(hostname),
			x509.DNSName(hostname + u'.local'),
			x509.IPAddress(ipaddress.IPv4Address(u'127.0.0.1')),
		]
		for ip in self._getLocalIPs():
			try:
				addr = ipaddress.ip_address(ip)
				entry = x509.IPAddress(addr)
				if entry not in san_names:
					san_names.append(entry)
			except Exception:
				pass

		cert = (
			x509.CertificateBuilder()
			.subject_name(subject)
			.issuer_name(subject)
			.public_key(key.public_key())
			.serial_number(x509.random_serial_number())
			.not_valid_before(now)
			.not_valid_after(now + datetime.timedelta(days=365 * 5))
			.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
			.add_extension(x509.SubjectAlternativeName(san_names), critical=False)
			.sign(key, hashes.SHA256(), default_backend())
		)

		key_pem = key.private_bytes(
			encoding=serialization.Encoding.PEM,
			format=serialization.PrivateFormat.TraditionalOpenSSL,
			encryption_algorithm=serialization.NoEncryption()
		).decode('utf-8')

		cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')

		return key_pem, cert_pem
