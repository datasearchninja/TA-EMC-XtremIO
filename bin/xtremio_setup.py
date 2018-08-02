import splunk.admin as admin
import splunk.entity as en
import os
import sys
import ConfigParser

SPLUNK_HOME = os.environ.get("SPLUNK_HOME")
myapp = __file__.split(os.sep)[-3]
EGG_DIR = SPLUNK_HOME + "/etc/apps/" + myapp + "/bin/"

for filename in os.listdir(EGG_DIR):
    if filename.endswith(".egg"):
        sys.path.append(EGG_DIR + filename)

import requests
from requests.auth import HTTPBasicAuth


class ConfigApp(admin.MConfigHandler):

    def setup(self):
        if self.requestedAction == admin.ACTION_EDIT:
            for arg in ['username', 'password', 'host']:
                self.supportedArgs.addOptArg(arg)

    def handleList(self, confInfo):
        confDict = self.readConf("xtremioappsetup")
        if None != confDict:
            for stanza, settings in confDict.items():
                for key, val in settings.items():
                    if stanza == 'setupentity':
                        confInfo[stanza].append(key, val)

    def handleEdit(self, confInfo):

        inputConfParser = ConfigParser.ConfigParser()
        inputConf = SPLUNK_HOME + "/etc/apps/" + myapp + "/local/inputs.conf"

        incConf = ConfigParser.ConfigParser()
        incFile = SPLUNK_HOME + "/etc/apps/" + myapp + "/default/include.conf"
        incConf.read(incFile)

        if incConf.has_section('include'):
            incStr = incConf.get('include', 'types')

        incList = incStr.split(',')

        username = self.callerArgs.data['username'][0]
        password = self.callerArgs.data['password'][0]
        host = self.callerArgs.data['host'][0]

        sessionKey = self.getSessionKey()
        owner = self.userName
        namespace = self.appName

        try:
            # Set XtremIO user name in splunk storage/password for encrypted security
            mon = en.getEntity('storage/passwords', '_new', sessionKey=sessionKey)
            mon["name"] = username
            mon["password"] = password
            mon["realm"] = host
            mon.namespace = namespace
            mon.owner = owner
            en.setEntity(mon, sessionKey=sessionKey)

            endpoint = "https://" + host + "/api/json/types"
            auth = HTTPBasicAuth(username, password)
            req_args = {"verify": False, "stream": False}
            if auth:
                req_args["auth"] = auth

            try:
                r = requests.get(endpoint, **req_args)
            except requests.exceptions.Timeout, e:
                print("HTTP Request Timeout error: %s" % str(e))
            except Exception as e:
                print("Exception performing request: %s" % str(e))

            inpFlag = False
            inp = en.getEntity('data/inputs/xtremio', '_new', sessionKey=sessionKey)

            try:
                r.raise_for_status()
                json_types = r.json()
                children = json_types["children"]
                for child in children:

                    if child['name'] not in incList:
                        continue

                    if inpFlag:
                        name = "xtremio://" + host + '::' + child["name"]
                        inputConfParser.add_section(name)

                        if child["name"] != "events":
                            endpoint = child["href"] + "/$get_ids$"
                        else:
                            endpoint = child["href"]

                        inputConfParser.set(name, 'endpoint', endpoint)
                        inputConfParser.set(name, 'sourcetype', "emc:xtremio:rest")
                        inputConfParser.set(name, 'polling_interval', 120)
                    else:
                        inp["name"] = host + '::' + child["name"]
                        if child["name"] != "events":
                            inp["endpoint"] = child["href"] + "/$get_ids$"
                        else:
                            inp["endpoint"] = child["href"]
                        inp["sourcetype"] = "emc:xtremio:rest"
                        inp["polling_interval"] = 120
                        inp.namespace = namespace
                        inp.owner = owner
                        inpFlag = True

                with open(inputConf, 'a+') as inputConfig:
                    inputConfParser.write(inputConfig)
                en.setEntity(inp, sessionKey=sessionKey)

            except requests.exceptions.HTTPError, e:
                print("HTTP Request error: %s" % str(e))

        except Exception, e:
            print "Exception: " + str(e)

# initialize the handler
admin.init(ConfigApp, admin.CONTEXT_NONE)
