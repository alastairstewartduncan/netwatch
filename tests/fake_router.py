"""A stand-in TP-Link EX client for tests and UI previews (mirrors a brsk EX820v)."""
from ipaddress import IPv4Address

from macaddress import EUI48
from tplinkrouterc6u.common.dataclass import Device, Firmware, IPv4DHCPLease, IPv4Status, Status
from tplinkrouterc6u.common.package_enum import Connection

CLIENTS = [
    (Connection.WIRED, "AA-BB-CC-00-00-01", "192.168.0.10", "DESKTOP-S5EOVAB"),
    (Connection.WIRED, "AA-BB-CC-00-00-02", "192.168.0.11", "NAS"),
    (Connection.HOST_5G, "AA-BB-CC-00-00-03", "192.168.0.20", "Alastairs-iPhone"),
    (Connection.HOST_5G, "AA-BB-CC-00-00-04", "192.168.0.21", "Claires-MacBook"),
    (Connection.HOST_2G, "AA-BB-CC-00-00-05", "192.168.0.30", "Hive-Hub"),
    (Connection.HOST_2G, "AA-BB-CC-00-00-06", "192.168.0.31", "ESP-Plug"),
    (Connection.GUEST_5G, "AA-BB-CC-00-00-07", "192.168.0.40", "Visitor-Phone"),
]


class Act:
    GL, GO = "gl", "go"

    def __init__(self, type, oid, stack="0,0,0,0,0,0", pstack="0,0,0,0,0,0", attrs=()):
        self.type, self.oid = type, oid


class FakeEX:
    ActItem = Act
    fail_login = False
    logins = 0
    logouts = 0
    uptime = 3 * 86400

    def __init__(self, host, password, username="admin", logger=None, verify_ssl=True, timeout=30):
        self.password = password

    def authorize(self):
        FakeEX.logins += 1
        if FakeEX.fail_login or self.password != "secret":
            raise Exception("TplinkRouter - EX - Login failed, wrong user or password.")

    def logout(self):
        FakeEX.logouts += 1

    def get_firmware(self):
        return Firmware("EX820v v1.0 00000000", "EX820v", "0.2.0 3.1.9 v6087.0 Build 241025 Rel.53781n")

    def get_status(self):
        s = Status()
        s._wan_ipv4_addr = IPv4Address("81.2.3.4")
        s._wan_ipv4_gateway = IPv4Address("81.2.3.1")
        s._lan_ipv4_addr = IPv4Address("192.168.0.1")
        s._lan_macaddr = EUI48("20-36-26-95-85-1B")
        s.wifi_2g_enable, s.wifi_5g_enable = True, True
        s.guest_2g_enable, s.guest_5g_enable = False, True
        s.cpu_usage, s.mem_usage = 0.12, 0.58
        s.devices = [Device(c, EUI48(m), IPv4Address(ip), h) for c, m, ip, h in CLIENTS]
        s.wired_total, s.wifi_clients_total, s.guest_clients_total = 2, 4, 1
        s.clients_total = 7
        return s

    def get_ipv4_status(self):
        v = IPv4Status()
        v._wan_ipv4_conntype = "IPoE"
        return v

    def get_ipv4_dhcp_leases(self):
        return [IPv4DHCPLease(EUI48(m), IPv4Address(ip), h, "23:10:00") for _, m, ip, h in CLIENTS]

    def req_act(self, acts):
        oid = acts[0].oid
        data = {
            "DEV2_ADT_WIFI_COMMON": [
                {"primaryEnable": "1", "guestEnable": "0", "SSID": "SKYCCF2E2", "channel": "3", "autoChannelEnable": "1",
                 "bandwidth": "20MHz", "KeyPassphrase": "should-be-scrubbed"},
                {"primaryEnable": "1", "guestEnable": "1", "SSID": "SKYCCF2E5-PRV", "guestSSID": "SKYCCF2E5",
                 "channel": "36", "autoChannelEnable": "1", "bandwidth": "160MHz"}],
            "DEV2_ADT_WAN": [{"enable": "1", "connStatusV4": "Connected", "X_TP_Uptime": "86400"}],
            "DEV2_ETHERNET_IF": [
                {"name": "LAN1", "status": "Down", "maxBitRate": "1000"},
                {"name": "LAN2", "status": "Down", "maxBitRate": "1000"},
                {"name": "LAN3", "status": "Up", "currentBitRate": "100", "maxBitRate": "1000"},
                {"name": "LAN4", "status": "Up", "currentBitRate": "2500", "maxBitRate": "2500"},
                {"name": "WAN", "status": "Up", "currentBitRate": "2500", "maxBitRate": "2500"}],
            "DEV2_DEV_INFO": {"modelName": "EX820v", "upTime": str(FakeEX.uptime)},
        }.get(oid)
        if data is None:
            raise Exception("bad oid")
        return "", [data]
