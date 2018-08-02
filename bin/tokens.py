import os
import sys
import logging

# dynamically load in any eggs in /etc/apps/snmp_ta/bin
SPLUNK_HOME = os.environ.get("SPLUNK_HOME")
myapp = __file__.split(os.sep)[-3]
EGG_DIR = SPLUNK_HOME + "/etc/apps/" + myapp + "/bin/"

for filename in os.listdir(EGG_DIR):
    if filename.endswith(".egg"):
        sys.path.append(EGG_DIR + filename)

import requests


def get_ids(raw_string, req_args):
    endpoint = raw_string.rsplit('/', 1)[0]
    name = endpoint.rsplit('/', 1)[1]
    endpoints = set()

    try:
        r = requests.get(endpoint, **req_args)
    except requests.exceptions.Timeout, e:
        logging.error("HTTP Request Timeout error: %s" % str(e))
    except Exception as e:
        logging.error("Exception performing request: %s" % str(e))

    try:
        r.raise_for_status()
        json_types = r.json()
        if name in ["ig-folders", "volume-folders"]:
            name = "folders"
        if name in ["clusters"]:
            sysname="name"
        else:
            sysname="sys-name"
        children = json_types[name]
        for child in children:
            logging.debug("href: %s" % child['href'])
            logging.debug("sys-name: %s" % child[sysname])
            url=child['href'] + "?cluster-name=" + child[sysname]
            endpoints.add(url)
    except requests.exceptions.HTTPError, e:
        logging.error("HTTP Request error: %s" % str(e))

    return endpoints
