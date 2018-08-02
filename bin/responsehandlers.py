import json
import ConfigParser
import os
import datetime

SPLUNK_HOME = os.environ.get("SPLUNK_HOME")
myapp = __file__.split(os.sep)[-3]


#the default handler , does nothing , just passes the raw output directly to STDOUT
class DefaultResponseHandler:
    def __init__(self, **args):
        pass

    def __call__(self, response_object, raw_response_output, response_type, req_args, endpoint, STANZA):

        if STANZA.split('::')[1] == 'events':
            r = json.loads(raw_response_output)
            events = r['events']
            if type(events) == list and len(events) > 0:
                timestamp = events[0]['timestamp']
                conf = ConfigParser.ConfigParser()
                fname = SPLUNK_HOME + "/etc/apps/" + myapp + "/local/events.ini"
                conf.read(fname)
                if conf.has_section(STANZA):
                    with open(fname, 'w+') as configfile:
                        conf.set(STANZA, 'timestamp', datetime.datetime.strptime(timestamp.split('.')[0], '%Y-%m-%d %H:%M:%S') + datetime.timedelta(seconds=1))
                        conf.write(configfile)

                output = {}
                for evnt in events:
                    output = {"events": evnt}
                    print_xml_stream(json.dumps(output))
        else:
            print_xml_stream(raw_response_output)


# prints XML stream
def print_xml_stream(s):
    print "<stream><event unbroken=\"1\"><data>%s</data><done/></event></stream>" % encodeXMLText(s)


def encodeXMLText(text):
    text = text.replace("&", "&amp;")
    text = text.replace("\"", "&quot;")
    text = text.replace("'", "&apos;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("\n", "")
    return text
