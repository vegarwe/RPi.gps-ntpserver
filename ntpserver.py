import serial
import logging
import struct
import time
import socket
import math
import threading
from RPi import GPIO

EPOCH = 2208988800
time_diff = None

class NMEADevice(threading.Thread):
    def __init__(self, pin_number, com_port, baudrate=38400):
        threading.Thread.__init__(self)
        self.keep_running = False
        self.log = logging.getLogger("nmea")
        self.pin_number = pin_number
        self.pps_time = None

        # Setup GPIO pins
        GPIO.setmode(GPIO.BCM)

        # GPIO 18 set up as inputs, pulled up to avoid false detection.
        GPIO.setup(self.pin_number, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # when a falling edge is detected on port 18, regardless of whatever
        # else is happening in the program, the function my_callback2 will be run
        # 'bouncetime=300' includes the bounce control written into interrupts2a.py
        GPIO.add_event_detect(self.pin_number, GPIO.FALLING, callback=self.pps_callback, bouncetime=300)

        # Open com port
        self.com = serial.Serial(com_port, baudrate, timeout=1)

    def readlines(self):
        # '$GPTXT,01,01,02,u-blox ag - www.u-blox.com*50\r\n$GPTXT,01,01,02,ANTARIS ATR062x HW 00040001*2E\r\n$GPTXT,01,01,02,EXT CORE       5.00    May 11 2006 14:40:17*72\r\n
        #  $GPTXT - text data
        #  $GPGGA - fix data
        #  $GPGLL - lat/lon
        #  $GPGSA - overall sat info
        #  $GPGSV - detailed sat info
        #  $GPRMC - minimum recommended data
        #  $GPVTG - vector track and speed over ground
        #  $GPZDA - data and time
        block = ''
        while self.keep_running:
            block += self.com.read(512)
            if block == '':
                continue
            lines = block.split('\r\n')
            for line in lines[:-1]:
                yield line
            block = lines[-1]

    def run(self):
        global time_diff
        self.keep_running = True
        for line in self.readlines():
            if not line.startswith('$GPZDA'):
                continue
            pps_time = self.get_and_clear_pps_time()
            if pps_time == None:
                continue
            # $GPZDA,112206.00,27,10,2013,00,00
            #gps_time = datetime.strptime(line[7:13] + line[16:27], '%H%M%S,%d,%m,%Y')
            time_tuple = (line[23:27], line[20:22], line[17:19],  # date
                    line[7:9], line[9:11], line[11:13],           # time
                    '0', '0', '0')                                # unused
            gps_time = time.mktime([int(i) for i in time_tuple])
            time_diff = (pps_time, gps_time, pps_time - gps_time)

    def pps_callback(self, channel):
        self.pps_time = time.time()

    def get_and_clear_pps_time(self):
        t = self.pps_time
        self.pps_time = None
        return t

    def close(self):
        nmea.keep_running = False
        self.join()
        self.com.close()
        GPIO.cleanup()

def decode_ntp(data):
    msg = struct.unpack('!2BH11I', data)
    return (
            ('li',               (msg[ 0] >> 6) & 0x03),
            ('status',           (msg[ 0]     ) & 0x3f),
            ('type',              msg[ 1]),
            ('prec',              msg[ 2]),
            ('est_error',         msg[ 3]),
            ('est_drift_rate',    msg[ 4]),
            ('ref_clock_id',      msg[ 5]),
            ('ref_time_int',      msg[ 6]),
            ('ref_time_frac',     msg[ 7]),
            ('orig_time_int',     msg[ 8]),
            ('orig_time_frac',    msg[ 9]),
            ('rec_time_int',      msg[10]),
            ('rec_time_frac',     msg[11]),
            ('trans_time_int',    msg[12]),
            ('trans_time_frac',   msg[13]),
            ('rec_time',          (msg[10]-EPOCH) + (msg[11] * 1.0 / 0x100000000L)),
            ('trans_time',        (msg[12]-EPOCH) + (msg[13] * 1.0 / 0x100000000L)),
        )

class NTPServer(object):
    #print '\tTime=%s' % time.ctime(msg[ 6]-EPOCH)
    def __init__(self, addr="127.0.0.1", port=123):
        self.log = logging.getLogger("ntp")
        self.keep_running = False
        self.sock = socket.socket(socket.AF_INET,    # Internet
                                  socket.SOCK_DGRAM) # UDP
        self.sock.bind((addr, port))

    def run(self):
        global time_diff
        while time_diff == None:
            time.sleep(0.01)

        self.keep_running = True
        while self.keep_running:
            data, addr = self.sock.recvfrom(1024) # buffer size is 1024 bytes
            r_frac, r_int = math.modf( time.time()+EPOCH+time_diff[2] )

            orig_time = struct.unpack("!2I", data[24:32])

            t_frac, t_int = math.modf( time.time()+EPOCH+time_diff[2] )
            out_values = (
                (0b00 << 6) | 28,         # No leap second, status OK. TODO: Why 28??????
                1,                        # Type primary reference (GPS)
                236,              #TODO   # Precision? Have no idea, but some value in
                648,              #TODO   # Estimated error? Again, I have not idea.
                440,              #TODO   # Drift rate? Wtf, why do I need all this...
                0x47505300,               # "GPS\x00" - GPS UHF positioning satellite.
                int(time_diff[0]),        # Reference time integer part, should be previous second
                0,                        # Reference time fractional part, should be 0
                orig_time[0],             # Originator time integer part
                orig_time[1],             # Originator time fractional part
                int(r_int)     ,          # Receive time integer part
                int(r_frac*0x100000000L), # Receive time fractional part
                int(t_int)     ,          # Receive time integer part
                int(t_frac*0x100000000L), # Receive time fractional part
            )
            if data:
                sent = self.sock.sendto(struct.pack('!2BH11I', *out_values), addr)

if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())

    ntp = NTPServer(port=1231)
    nmea = NMEADevice(18, '/dev/ttyACM0')

    try:
        nmea.start()
        ntp.run()
    finally:
        # clean up on CTRL+C or normal exit
        nmea.close()

