###########################################################
#                    Simple NTP Program                   #
#                    By  Maxin B. John (www.linuxify.net) #
#   Simple NTP Client program with command line option    #
###########################################################
from socket import *
import struct
import sys
import time
from optparse import OptionParser

from fisken import decode_ntp

parser = OptionParser()
parser.add_option("-s","--server",dest="server", default='0.fedora.pool.ntp.org', help="NTP server to contact, default 0.fedora.pool.ntp.org")
parser.add_option("-p","--port",  dest="port",   default=123, type='int',         help="NTP server port")
(options,args) = parser.parse_args()

EPOCH = 2208988800L
client = socket( AF_INET, SOCK_DGRAM )
data = '\x1b' + 47 * '\0'
try:
    client.sendto( data, ( options.server, options.port ))
    data, address = client.recvfrom( 1024 )

    print repr(data)
    fields = decode_ntp(data)
    for field in fields:
      print '%17s %r' % (field[0], field[1])

    if data:
        print 'Response received from:', address
        t = struct.unpack( '!12I', data )[10]
        print '\tTime=%s' % time.ctime(t-EPOCH)
except gaierror:
    print "Network error "
except error:
    print "Error!"
