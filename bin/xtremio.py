import sys
import logging
import os
import time
import re
import xml.dom.minidom
import ConfigParser

import tokens


SPLUNK_HOME = os.environ.get("SPLUNK_HOME")

RESPONSE_HANDLER_INSTANCE = None
SPLUNK_PORT = 8089
STANZA = None
SESSION_TOKEN = None
REGEX_PATTERN = None

# dynamically load in any eggs in /etc/apps/snmp_ta/bin
myapp = __file__.split(os.sep)[-3]
EGG_DIR = SPLUNK_HOME + "/etc/apps/" + myapp + "/bin/"

for filename in os.listdir(EGG_DIR):
    if filename.endswith(".egg"):
        sys.path.append(EGG_DIR + filename)

import requests
from requests.auth import HTTPBasicAuth
import splunk.entity as entity

# set up logging
logging.root
logging.root.setLevel(logging.ERROR)
formatter = logging.Formatter('%(levelname)s %(message)s')
# with zero args , should go to STD ERR
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logging.root.addHandler(handler)

SCHEME = """<scheme>
    <title>XtremIO REST Inputs</title>
    <description>REST API input for polling data from EMC XtremIO</description>
    <use_external_validation>true</use_external_validation>
    <streaming_mode>xml</streaming_mode>
    <use_single_instance>false</use_single_instance>

    <endpoint>
        <args>
            <arg name="name">
                <title>REST input name</title>
                <description>Name of this REST input</description>
            </arg>
            <arg name="endpoint">
                <title>Endpoint URL</title>
                <description>URL to send the HTTP GET request to</description>
                <required_on_edit>false</required_on_edit>
                <required_on_create>true</required_on_create>
            </arg>
            <arg name="polling_interval">
                <title>Polling Interval</title>
                <description>Interval time in seconds to poll the endpoint</description>
                <required_on_edit>false</required_on_edit>
                <required_on_create>false</required_on_create>
            </arg>
        </args>
    </endpoint>
</scheme>
"""


def do_validate():
    get_validation_config()


# access the credentials in /servicesNS/nobody/<YourApp>/storage/passwords
def getCredentials(sessionKey, host):
    myapp = __file__.split(os.sep)[-3]
    try:
        # list all credentials
        entities = entity.getEntities(['admin', 'passwords'], namespace=myapp, owner='nobody', sessionKey=sessionKey)
    except Exception, e:
        logging.error("Could not get %s credentials from splunk. Error: %s" % (myapp, str(e)))

    # return first set of credentials
    for i, c in entities.items():
        if host == c['realm']:
            return c['username'], c['clear_password']

    logging.error("No credentials have been found")


def do_run():
    config = get_input_config()

    #setup some globals
    server_uri = config.get("server_uri")
    global SPLUNK_PORT
    global STANZA
    global SESSION_TOKEN
    SPLUNK_PORT = server_uri[18:]
    STANZA = config.get("name")
    SESSION_TOKEN = config.get("session_key")

    #params
    original_endpoint = config.get("endpoint")
    host = STANZA.split('::')[0].split('//')[1]
    json_type = STANZA.split('::')[1]

    #for basic and digest
    auth_user, auth_password = getCredentials(SESSION_TOKEN, host)
    polling_interval = int(config.get("polling_interval", 60))

    backoff_time = 60

    response_type = "json"

    response_handler = config.get("response_handler", "DefaultResponseHandler")
    module = __import__("responsehandlers")
    class_ = getattr(module, response_handler)

    global RESPONSE_HANDLER_INSTANCE
    RESPONSE_HANDLER_INSTANCE = class_()

    try:
        auth = HTTPBasicAuth(auth_user, auth_password)

        req_args = {"verify": False, "stream": False}

        if auth:
            req_args["auth"] = auth

        while True:

            if json_type == 'events':
                conf = ConfigParser.ConfigParser()
                fname = SPLUNK_HOME + "/etc/apps/" + myapp + "/local/events.ini"
                conf.read(fname)
                if not conf.has_section(STANZA):
                    conf.add_section(STANZA)
                    with open(fname, 'w+') as configfile:
                        conf.set(STANZA, 'timestamp', "None")
                        conf.write(configfile)
                else:
                    timestamp = conf.get(STANZA, "timestamp")
                    if timestamp != 'None':
                        req_args["params"] = {"from-date-time": timestamp}

            #token replacement
            if json_type == 'events':
                endpoints = []
                endpoints.append(original_endpoint)
            else:
                endpoints = replaceTokens(original_endpoint, req_args)

            for endpoint in endpoints:

                try:
                    r = requests.get(endpoint, **req_args)
                except requests.exceptions.Timeout, e:
                    logging.error("HTTP Request Timeout error: %s" % str(e))
                    time.sleep(float(backoff_time))
                except Exception as e:
                    logging.error("Exception performing request: %s" % str(e))
                    time.sleep(float(backoff_time))

                try:
                    r.raise_for_status()
                    handle_output(r, r.text, response_type, req_args, endpoint, STANZA)
                except requests.exceptions.HTTPError, e:
                    logging.error("HTTP Request error: %s for endpoint %s" % (str(e), str(endpoint)))
                    time.sleep(float(backoff_time))

            time.sleep(float(polling_interval))

    except RuntimeError, e:
        logging.error("Looks like an error: %s" % str(e))
        sys.exit(2)


def replaceTokens(raw_string, req_args):
    try:
        substitution_tokens = re.findall("\$(?:\w+)\$", raw_string)
        for token in substitution_tokens:
            endpoints = getattr(tokens, token[1:-1])(raw_string, req_args)
        return endpoints
    except:
        e = sys.exc_info()[1]
        logging.error("Looks like an error substituting tokens: %s" % str(e))


def handle_output(response, output, type, req_args, endpoint, STANZA):
    try:
        if REGEX_PATTERN:
            search_result = REGEX_PATTERN.search(output)
            if search_result is None:
                return
        RESPONSE_HANDLER_INSTANCE(response, output, type, req_args, endpoint, STANZA)
        sys.stdout.flush()
    except RuntimeError, e:
        logging.error("Looks like an error handle the response output: %s" % str(e))


# prints validation error data to be consumed by Splunk
def print_validation_error(s):
    print "<error><message>%s</message></error>" % encodeXMLText(s)


# prints XML stream
def print_xml_single_instance_mode(s):
    print "<stream><event><data>%s</data></event></stream>" % encodeXMLText(s)


# prints simple stream
def print_simple(s):
    print "%s\n" % s


def encodeXMLText(text):
    text = text.replace("&", "&amp;")
    text = text.replace("\"", "&quot;")
    text = text.replace("'", "&apos;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def usage():
    print "usage: %s [--scheme|--validate-arguments]"
    logging.error("Incorrect Program Usage")
    sys.exit(2)


def do_scheme():
    print SCHEME


#read XML configuration passed from splunkd, need to refactor to support single instance mode
def get_input_config():
    config = {}

    try:
        # read everything from stdin
        config_str = sys.stdin.read()

        # parse the config XML
        doc = xml.dom.minidom.parseString(config_str)
        root = doc.documentElement

        session_key_node = root.getElementsByTagName("session_key")[0]
        if session_key_node and session_key_node.firstChild and session_key_node.firstChild.nodeType == session_key_node.firstChild.TEXT_NODE:
            data = session_key_node.firstChild.data
            config["session_key"] = data

        server_uri_node = root.getElementsByTagName("server_uri")[0]
        if server_uri_node and server_uri_node.firstChild and server_uri_node.firstChild.nodeType == server_uri_node.firstChild.TEXT_NODE:
            data = server_uri_node.firstChild.data
            config["server_uri"] = data

        conf_node = root.getElementsByTagName("configuration")[0]
        if conf_node:
            logging.debug("XML: found configuration")
            stanza = conf_node.getElementsByTagName("stanza")[0]
            if stanza:
                stanza_name = stanza.getAttribute("name")
                if stanza_name:
                    logging.debug("XML: found stanza " + stanza_name)
                    config["name"] = stanza_name

                    params = stanza.getElementsByTagName("param")
                    for param in params:
                        param_name = param.getAttribute("name")
                        logging.debug("XML: found param '%s'" % param_name)
                        if param_name and param.firstChild and param.firstChild.nodeType == param.firstChild.TEXT_NODE:
                            data = param.firstChild.data
                            config[param_name] = data
                            logging.debug("XML: '%s' -> '%s'" % (param_name, data))

        checkpnt_node = root.getElementsByTagName("checkpoint_dir")[0]
        if checkpnt_node and checkpnt_node.firstChild and checkpnt_node.firstChild.nodeType == checkpnt_node.firstChild.TEXT_NODE:
            config["checkpoint_dir"] = checkpnt_node.firstChild.data

        if not config:
            raise Exception("Invalid configuration received from Splunk.")

    except Exception, e:
        raise Exception("Error getting Splunk configuration via STDIN: %s" % str(e))

    return config


#read XML configuration passed from splunkd, need to refactor to support single instance mode
def get_validation_config():
    val_data = {}

    # read everything from stdin
    val_str = sys.stdin.read()

    # parse the validation XML
    doc = xml.dom.minidom.parseString(val_str)
    root = doc.documentElement

    logging.debug("XML: found items")
    item_node = root.getElementsByTagName("item")[0]
    if item_node:
        logging.debug("XML: found item")

        name = item_node.getAttribute("name")
        val_data["stanza"] = name

        params_node = item_node.getElementsByTagName("param")
        for param in params_node:
            name = param.getAttribute("name")
            logging.debug("Found param %s" % name)
            if name and param.firstChild and param.firstChild.nodeType == param.firstChild.TEXT_NODE:
                val_data[name] = param.firstChild.data

    return val_data


if __name__ == '__main__':

    if len(sys.argv) > 1:
        if sys.argv[1] == "--scheme":
            do_scheme()
        elif sys.argv[1] == "--validate-arguments":
            do_validate()
        else:
            usage()
    else:
        do_run()

    sys.exit(0)
