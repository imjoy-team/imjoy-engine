"""
Parser for engine.io protocol

This implementation is largely inspired from the package python-engineio
written by Miguel Grinberg and available under the MIT license at
https://github.com/miguelgrinberg/python-engineio
"""

import six
import json

binary_types = (six.binary_type, bytearray)

class Packet(object):
    OPEN    = 0
    CLOSE   = 1
    PING    = 2
    PONG    = 3
    MESSAGE = 4
    UPGRADE = 5
    NOOP    = 6

    def __init__(self, _type, data='', binary=False):
        self.type = _type
        self.data = data
        self.binary = binary

    @property
    def type_string(self):
        return {
            self.OPEN:     'open',
            self.CLOSE:    'close',
            self.PING:     'ping',
            self.PONG:     'pong',
            self.MESSAGE:  'message',
            self.UPGRADE:  'upgrade',
            self.NOOP:     'noop'
        }[self.type]

class Parser(object):
    def decode_packet(self, encoded_packet):
        """Decode a transmitted package."""
        b64 = False
        if not isinstance(encoded_packet, binary_types):
            encoded_packet = encoded_packet.encode('utf-8')
        elif not isinstance(encoded_packet, bytes):
            encoded_packet = bytes(encoded_packet)
        packet_type = six.byte2int(encoded_packet[0:1])
        if packet_type == 98:  # 'b' --> binary base64 encoded packet
            binary = True
            encoded_packet = encoded_packet[1:]
            packet_type = six.byte2int(encoded_packet[0:1])
            packet_type -= 48
            b64 = True
        elif packet_type >= 48:
            packet_type -= 48
            binary = False
        else:
            binary = True
        packet_data = None
        if len(encoded_packet) > 1:
            if binary:
                if b64:
                    packet_data = base64.b64decode(encoded_packet[1:])
                else:
                    packet_data = encoded_packet[1:]
            else:
                packet_data = encoded_packet[1:].decode('utf-8')

        return Packet(packet_type, packet_data, binary)


    def encode_packet(self, packet, b64=False, always_bytes=False):
        """Encode the packet for transmission."""
        if packet.binary and not b64:
            encoded_packet = six.int2byte(packet.type)
        else:
            encoded_packet = six.text_type(packet.type)
            if packet.binary and b64:
                encoded_packet = 'b' + encoded_packet
        if packet.binary:
            if b64:
                encoded_packet += base64.b64encode(packet.data).decode('utf-8')
            else:
                encoded_packet += packet.data
        elif isinstance(packet.data, six.string_types):
            encoded_packet += packet.data
        elif isinstance(packet.data, dict) or isinstance(packet.data, list):
            encoded_packet += json.dumps(packet.data,
                                              separators=(',', ':'))
        elif packet.data is not None:
            encoded_packet += str(packet.data)
        if always_bytes and not isinstance(encoded_packet, binary_types):
            encoded_packet = encoded_packet.encode('utf-8')
        return encoded_packet


    def decode_payload(self, bytes):
        """Decode a received payload."""
        packets = []
        while bytes:
            if six.byte2int(bytes[0:1]) <= 1:
                packet_len = 0
                i = 1
                while six.byte2int(bytes[i:i + 1]) != 255:
                    packet_len = packet_len * 10 + six.byte2int(bytes[i:i + 1])
                    i += 1
                packet_start = i+1
            else:
                i = bytes.find(b':')
                if i == -1:
                    raise ValueError('Invalid payload')
                packet_len = int(bytes[0:i])
                packet_start = i+1

            packet = self.decode_packet(bytes[packet_start:packet_start+packet_len])
            packets.append(packet)
            bytes = bytes[packet_start+packet_len:]

        return packets

    def encode_payload(self, packets, b64=False):
        """Encode the payload to be sent."""
        bytes = b''
        for packet in packets:
            packet_bytes = self.encode_packet(packet, b64)
            packet_len = len(packet_bytes)
            if b64:
                bytes += str(packet_len) + b':' + packet_bytes
            else:
                binary_len = b''
                while packet_len != 0:
                    binary_len = six.int2byte(packet_len % 10) + binary_len
                    packet_len = int(packet_len / 10)
                bytes += b'\x01' if packet.binary else b'\x00'
                bytes += binary_len + b'\xff' + packet_bytes
        return bytes
