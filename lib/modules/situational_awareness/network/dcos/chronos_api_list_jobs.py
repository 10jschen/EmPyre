from lib.common import helpers

class Module:

    def __init__(self, mainMenu, params=[]):

        # metadata info about the module, not modified during runtime
        self.info = {
            # name for the module that will appear in module menus
            'Name': 'Chronos API List Jobs',

            # list of one or more authors for the module
            'Author': ['@TweekFawkes'],

            # more verbose multi-line description of the module
            'Description': ('List Chronos jobs using the HTTP API service for the Chronos Framework'),

            # True if the module needs to run in the background
            'Background' : False,

            # File extension to save the file as
            'OutputExtension': "json",

            # if the module needs administrative privileges
            'NeedsAdmin' : False,

            # True if the method doesn't touch disk/is reasonably opsec safe
            'OpsecSafe' : True,
            
            # list of any references/other comments
            'Comments': ["Docs: https://mesosphere.github.io/mesos-dns/docs/http.html", "Source Code: https://github.com/mesosphere/mesos-dns/blob/master/resolver/resolver.go"]
        }

        # any options needed by the module, settable during runtime
        self.options = {
            # format:
            #   value_name : {description, required, default_value}
            'Agent' : {
                # The 'Agent' option is the only one that MUST be in a module
                'Description'   :   'Agent to execute module on.',
                'Required'      :   True,
                'Value'         :   ''
            },
            'Target' : {
                # The 'Agent' option is the only one that MUST be in a module
                'Description'   :   'FQDN, domain name, or hostname to lookup on the remote target.',
                'Required'      :   True,
                'Value'         :   'chronos.mesos'
            },
            'Port' : {
                # The 'Agent' option is the only one that MUST be in a module
                'Description'   :   'The port to connect to.',
                'Required'      :   True,
                'Value'         :   '8080'
            }
        }

        # save off a copy of the mainMenu object to access external functionality
        #   like listeners/agent handlers/etc.
        self.mainMenu = mainMenu

        # During instantiation, any settable option parameters
        #   are passed as an object set to the module and the
        #   options dictionary is automatically set. This is mostly
        #   in case options are passed on the command line
        if params:
            for param in params:
                option, value = param
                if option in self.options:
                    self.options[option]['Value'] = value


    def generate(self):
        target = self.options['Target']['Value']
        port = self.options['Port']['Value']
        

        script = """
import urllib2

target = "%s"
port = "%s"

url = "http://" + target + ":" + port + "/scheduler/jobs"

try:
    request = urllib2.Request(url)
    request.add_header('User-Agent',
                   'Mozilla/6.0 (X11; Linux x86_64; rv:24.0) '
                   'Gecko/20140205     Firefox/27.0 Iceweasel/25.3.0')
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    content = opener.open(request).read()
    print str(content)
except Exception as e:
    print "Failure sending payload: " + str(e)

""" %(target, port)

        return script
