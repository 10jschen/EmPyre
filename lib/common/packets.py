"""

Packet handling functionality for EmPyre.

Defines packet types, generates/validates epoch counters,
builds tasking packets and parses result packets


    Packet format:

            [4 bytes] - type
            [4 bytes] - counter
            [4 bytes] - length
            [X...]    - tasking data


    *_SAVE packets have the sub format:

            [15 chars] - save prefix
            [5 chars]  - extension
            [X...]     - tasking data

"""


import struct
import time


# 0         -> error
# 1-99      -> standard functionality
# 100-199   -> dynamic functionality
# 200-299   -> SMB functionality

PACKET_NAMES = {
    "ERROR" : 0,

    "TASK_SYSINFO"   : 1,
    "TASK_EXIT"   : 2,

    "TASK_SET_DELAY" : 10,
    "TASK_GET_DELAY" : 12,
    "TASK_SET_SERVERS" : 13,
    "TASK_ADD_SERVERS" : 14,
    "TASK_UPDATE_PROFILE" : 20,
    "TASK_SET_KILLDATE" : 30,
    "TASK_GET_KILLDATE" : 31,
    "TASK_SET_WORKING_HOURS" : 32,
    "TASK_GET_WORKING_HOURS" : 33,

    "TASK_SHELL" : 40,
    "TASK_DOWNLOAD" : 41,
    "TASK_UPLOAD" : 42,

    "TASK_GETJOBS" : 50,
    "TASK_STOPJOB" : 51,

    "TASK_CMD_WAIT" : 100,
    "TASK_CMD_WAIT_SAVE" : 101,
    "TASK_CMD_WAIT_DISK" : 102,
    "TASK_CMD_JOB" : 110,
    "TASK_CMD_JOB_SAVE" : 111,
    "TASK_MODULE_IMPORT" : 122,
    "TASK_MODULE_REMOVE" : 123,
    "TASK_MODULE_VIEW" : 124,

    "TASK_SMBWAIT" : 200,
    "TASK_SMBWAIT_SAVE" : 201,
    "TASK_SMBNOWAIT" : 210,
    "TASK_SMBNOWAIT_SAVE" : 211,
}

# build a lookup table for packet IDs
PACKET_IDS = {}
for name, ID in PACKET_NAMES.items():
    PACKET_IDS[ID] = name


def get_counter():
    """
    Derives a 32-bit counter based on the epoch.
    """
    return int(time.time())


def validate_counter(counter):
    """
    Validates a counter ensuring it's in a sliding window.
    Window is +/- 10 minutes (600 seconds).
    """
    # currentTime = int(time.time())
    # return (currentTime-600) <= counter <= (currentTime+600)
    return True


def build_task_packet(taskName, data):
    """
    Build a task packet for an agent.

        [4 bytes] - type
        [4 bytes] - counter
        [4 bytes] - length
        [X...]    - tasking data
    """

    taskID = struct.pack('=L', PACKET_NAMES[taskName])
    counter = struct.pack('=L', get_counter())
    length = struct.pack('=L', len(data))
    return taskID + counter + length + data.encode('ascii', errors='ignore')


def parse_result_packet(packet, packetOffset=0):
    """
    Parse a result packet-

    Returns a tuple with (responseName, counter, length, data, remainingData)
    """

    try:
        responseID = struct.unpack('=L', packet[0+packetOffset:4+packetOffset])[0]
        counter = struct.unpack('=L', packet[4+packetOffset:8+packetOffset])[0]
        length = struct.unpack('=L', packet[8+packetOffset:12+packetOffset])[0]
        data = packet[12+packetOffset:12+packetOffset+length]

        # if isinstance(data, unicode):
        #    print "UNICODE DATA"
        # elif isinstance(data, str):
        #    print "ASCII / UTF8"
        remainingData = packet[12+packetOffset+length:]
        return (PACKET_IDS[responseID], counter, length, data, remainingData)
    except Exception:
        return (None, None, None, None, None)


def parse_result_packets(packets):
    """
    Parse a blob of one or more result packets
    """

    resultPackets = []

    # parse the first result packet
    (responseName, counter, length, data, remainingData) = parse_result_packet(packets)

    if responseName and responseName != '':
        resultPackets.append((responseName, counter, length, data))

    offset = 12 + length

    while (remainingData and remainingData != ""):
        # parse any additional result packets
        (responseName, counter, length, data, remainingData) = parse_result_packet(packets, packetOffset=offset)

        if responseName and responseName != '':
            resultPackets.append((responseName, counter, length, data))

        offset += 12 + length

    return resultPackets


def resolve_id(ID):
    """
    Resolve a packet ID to its key.
    """
    return PACKET_IDS[int(ID)]
