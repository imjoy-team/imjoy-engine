import six
import json
from collections import namedtuple
from base64 import b64encode
from copy import deepcopy

from .symmetries import (
    decode_string,
    encode_string,
    get_byte,
    get_character,
    get_int,
    parse_url,
)


EngineIOSession = namedtuple(
    "EngineIOSession", ["id", "ping_interval", "ping_timeout", "transport_upgrades"]
)


class SocketIOPacket:
    def __init__(self, packet_type, path, ack_id, args, attachments):
        self.type = packet_type
        self.path = path
        self.ack_id = ack_id
        self.args = args
        self.attachments = attachments
        self.binary_packets = []

    def __repr__(self):
        return (
            "<SocketIOPacket type: %s, path: %s, ack_id: %s, args: %s, attach: %s>"
            % (self.type, self.path, self.ack_id, self.args, self.attachments)
        )

    @property
    def finished(self):
        return self.attachments == len(self.binary_packets)

    def add(self, packet):
        self.binary_packets.append(packet)
        if self.finished:
            self.replace_placeholders()

    def replace_placeholders(self):
        def predicate(obj):
            if type(obj) is dict:
                return "_placeholder" in obj and "num" in obj
            else:
                return False

        def fn(obj):
            return bytearray(self.binary_packets[obj["num"]])

        self.args = traverse(deepcopy(self.args), predicate, fn)


def traverse(obj, predicate, fn):
    if predicate(obj):
        return fn(obj)
    elif isinstance(obj, dict):
        for key, value in six.iteritems(obj):
            obj[key] = traverse(value, predicate, fn)
        return obj
    elif isinstance(obj, (tuple, list)):
        obj = list(obj)
        for i, value in enumerate(obj):
            obj[i] = traverse(value, predicate, fn)
        return obj
    else:
        return obj


def parse_host(host, port, resource):
    if not host.startswith("http"):
        host = "http://" + host
    url_pack = parse_url(host)
    is_secure = url_pack.scheme == "https"
    port = port or url_pack.port or (443 if is_secure else 80)
    url = "%s:%d%s/%s" % (url_pack.hostname, port, url_pack.path, resource)
    return is_secure, url


def parse_engineIO_session(engineIO_packet_data):
    d = json.loads(decode_string(engineIO_packet_data))
    return EngineIOSession(
        id=d["sid"],
        ping_interval=d["pingInterval"] / float(1000),
        ping_timeout=d["pingTimeout"] / float(1000),
        transport_upgrades=d["upgrades"],
    )


def encode_engineIO_content(engineIO_packets):
    content = bytearray()
    for packet_type, packet_data in engineIO_packets:
        packet_text = format_packet_text(packet_type, packet_data)
        content.extend(_make_packet_prefix(packet_text) + packet_text)
    return content


def decode_engineIO_content(content):
    content_index = 0
    content_length = len(content)
    while content_index < content_length:
        content_index, packet_length = _read_packet_length(content, content_index)
        content_index, packet_text = _read_packet_text(
            content, content_index, packet_length
        )
        engineIO_packet_type, engineIO_packet_data = parse_packet_text(packet_text)
        yield engineIO_packet_type, engineIO_packet_data


def format_socketIO_packet_data(path=None, ack_id=None, args=None):
    binary_packets = []

    def predicate(obj):
        return isinstance(obj, bytearray)

    def fn(data):
        binary_packets.append(bytearray(b64encode(six.binary_type(data))))
        return {"_placeholder": True, "num": len(binary_packets) - 1}

    args = traverse(deepcopy(args), predicate, fn)
    socketIO_packet_data = json.dumps(args, ensure_ascii=False) if args else ""
    if ack_id is not None:
        socketIO_packet_data = str(ack_id) + socketIO_packet_data
    if path:
        socketIO_packet_data = path + "," + socketIO_packet_data
    if binary_packets:
        socketIO_packet_data = "%s-%s" % (len(binary_packets), socketIO_packet_data)
    return socketIO_packet_data, binary_packets


def parse_socketIO_packet(socketIO_packet):
    packet_type = get_int(socketIO_packet, 0)

    packet = decode_string(socketIO_packet[1:])
    # Binary types
    if packet_type in [5, 6]:
        attachments, packet = packet.split("-", 1)
    else:
        attachments = "0"

    if packet.startswith("/"):
        try:
            path, packet = packet.split(",", 1)
        except ValueError:
            path = packet
            packet = ""
    else:
        path = ""

    try:
        ack_id_string, packet = packet.split("[", 1)
        packet = "[" + packet
        ack_id = int(ack_id_string)
    except (ValueError, IndexError):
        ack_id = None

    try:
        args = json.loads(packet)
    except ValueError:
        args = []
    return SocketIOPacket(packet_type, path, ack_id, args, int(attachments))


def format_packet_text(packet_type, packet_data):
    if isinstance(packet_data, bytearray):
        packet_data = packet_data.decode("utf-8")
    return encode_string(str(packet_type) + packet_data)


def parse_packet_text(packet_text):
    packet_type = get_int(packet_text, 0)
    packet_data = packet_text[1:]
    return packet_type, packet_data


def get_namespace_path(socketIO_packet_data):
    if not socketIO_packet_data.startswith(b"/"):
        return ""
    # Loop incrementally in case there is binary data
    parts = []
    for i in range(len(socketIO_packet_data)):
        character = get_character(socketIO_packet_data, i)
        if "," == character:
            break
        parts.append(character)
    return "".join(parts)


def _make_packet_prefix(packet):
    length_string = str(len(packet))
    header_digits = bytearray([0])
    for i in range(len(length_string)):
        header_digits.append(ord(length_string[i]) - 48)
    header_digits.append(255)
    return header_digits


def _read_packet_length(content, content_index):
    while get_byte(content, content_index) not in [0, 1]:
        content_index += 1
    content_index += 1
    packet_length_string = ""
    byte = get_byte(content, content_index)
    while byte != 255:
        packet_length_string += str(byte)
        content_index += 1
        byte = get_byte(content, content_index)
    return content_index, int(packet_length_string)


def _read_packet_text(content, content_index, packet_length):
    while get_byte(content, content_index) == 255:
        content_index += 1
    packet_text = content[content_index : content_index + packet_length]
    return content_index + packet_length, packet_text
