#!/usr/bin/env python3

# python standard libraries
import __main__, sys, os, signal, pprint, configparser, argparse, logging, logging.handlers, time, random, copy

# Raspberry Pi specific libraries
import pigpio


#### Global Variables ####

# ws2812svr constants
ws281xPWMchannel = 2
ws281xNeopixelPin = 13
ws281xBrightness = 255/2
ws281xInvert = 0
ws281xLedCount = 0 # will be calculated later, from the INI file
ws281xLedType = 1

colors = { 'off' : '000000',
           'red' : 'FF0000',
           'grn' : '00FF00',
           'blu' : '0000FF',
           'ylw' : 'FFFF00',
           'brw' : '7F2805',
           'prp' : 'B54A8F',
           'wht' : 'FFFFFF'
         }

pp = pprint.PrettyPrinter(indent=4) # Setup format for pprint.
fn = os.path.splitext(os.path.basename(__main__.__file__))[0]
args = None
config = None

last = [None]*32
cb = []

def cbf(GPIO, level, tick):
    #print("G={} l={}".format(GPIO, level))
    for section in config.keys(): 
      if config[section]['gpio_pin'].isdigit() and int(config[section]['gpio_pin']) == GPIO:
          logger.debug('gpio_pin = ' + str(GPIO )+ ' Section "' + section + '"')

def main():
  global ws281xLedCount
  
  ParseArgs()
  setupLogging()
  
  # initialize CTRL-C Exit handler
  signal.signal(signal.SIGINT, signal_handler)

  
  # and determine maximum LED position
  ws281xLedCount = 0
  buttonPins = []

  for section in config.keys():
    maxTemp = int(config[section]['led_start']) + int(config[section]['led_length'])
    logger.debug("section = " + section + ", led_start = " + config[section]['led_start'] + ", gpio_pin = " + config[section]['gpio_pin'] + ", led_length = " + config[section]['led_length'] + ", ws281xLedCount = " + str(ws281xLedCount-1) )
    if maxTemp > ws281xLedCount:
      ws281xLedCount = maxTemp
    if config[section]['gpio_pin'].isdigit():
      buttonPins.append(int(config[section]['gpio_pin']))
    
  logger.debug("Max LED position found to be " + str(ws281xLedCount - 1))
  buttonPins = list(set(buttonPins))
  logger.debug("list of pins = " + pp.pformat(buttonPins))

  #### POST - Neopixel Pre Operating Self Tests ####
  logger.debug("initializing ws2812svr")
  write_ws281x('setup {0},{1},{2},{3},{4},{5}\ninit\n'.format(ws281xPWMchannel, ws281xLedCount, ws281xLedType, ws281xInvert, ws281xBrightness, ws281xNeopixelPin))
  for colorName in ['red', 'grn', 'blu', 'off']:
    logger.debug("POST LED test of ALL " + colorName)
    write_ws281x('fill ' + str(ws281xPWMchannel) + ',' + colors[colorName] + '\nrender\n')
    time.sleep(args.postDelay)

  #### used to locate LEDs on device
  if args.walkLED:
    walk_leds()
  
  #### stop if command line requested.
  if args.stop :
    logger.info('Option set to just initialize and then quit')
    quit()

  pi = pigpio.pi()
  if not pi.connected:
     exit()

     
  for buttonPin in buttonPins:
     pi.set_mode(buttonPin, pigpio.INPUT)
     pi.set_pull_up_down(buttonPin, pigpio.PUD_UP)
     pi.set_glitch_filter(buttonPin, 100)
     cb.append(pi.callback(buttonPin, pigpio.FALLING_EDGE, cbf))

  #### Main Loop
  try:
     while True:
        time.sleep(60)
  except KeyboardInterrupt:
     print("\nTidying up")
     for c in cb:
        c.cancel()
  pi.stop()

#end of main():

def walk_leds():
  global ws281xLedCount
  for pos in range(ws281xLedCount):
    write_ws281x('fill ' + str(ws281xPWMchannel) + ',' + \
                           colors['red']  + ',' + \
                           str(pos) + ',' + \
                           '1' + \
                           '\nrender\n')
    logger.debug('LED Index = ' + str(pos))

    try:
        eval(input("Press enter to continue"))
    except SyntaxError:
        pass
    
    write_ws281x('fill ' + str(ws281xPWMchannel) + ',' + colors['off'] + '\nrender\n')
    pos = pos + 1
  exit()

def ParseArgs():
  global args
  global config
  global fn
  
  # Get filename of running script without path and or extension.

  # Define command line arguments
  parser = argparse.ArgumentParser(description='Raspberry Pi MegaOperation board game.')
  parser.add_argument('--verbose', '-v', action='count', help='verbose multi level', default=1)
  parser.add_argument('--config', '-c', help='specify config file', default=(os.path.join(os.path.dirname(os.path.realpath(__file__)), fn + ".ini")))
  parser.add_argument('--ws281x', '-w', help='specify ws281x file handle', default="/dev/ws281x")
  parser.add_argument('--stop', '-s', action='store_true', help='just initialize and stop')
  parser.add_argument('--postDelay', '-p', help='specify the LED delays at startup', type=float, default="0.25")
  parser.add_argument('--walkLED', '-L', action='store_true', help='move LED increamentally, with standard input, used for determining LED positions.')

  # Read in and parse the command line arguments
  args = parser.parse_args()

  os.path.join(os.path.dirname(os.path.realpath(__file__)), args.config)


  # Read in configuration file and create dictionary object
  configParse = configparser.ConfigParser()
  configParse.read(args.config)
  config = {s:dict(configParse.items(s)) for s in configParse.sections()}
# end of ParseArgs():

logger = None
def setupLogging():
  global args
  global config
  global fn
  global logger
  
  # Setup display and file logging with level support.
  logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
  logger = logging.getLogger()
  fileHandler = logging.handlers.RotatingFileHandler("{0}/{1}.log".format('/var/log/'+ fn +'/', fn), maxBytes=2*1024*1024, backupCount=2)

  fileHandler.setFormatter(logFormatter)
  #fileHandler.setLevel(logging.DEBUG)
  logger.addHandler(fileHandler)

  consoleHandler = logging.StreamHandler()
  #consoleHandler.setLevel(logging.DEBUG)
  consoleHandler.setFormatter(logFormatter)
  logger.addHandler(consoleHandler)

  # Dictionary to translate Count of -v's to logging level
  verb = { 0 : logging.WARN,
           1 : logging.INFO,
           2 : logging.DEBUG,
         }

  # zero adjust for zero offset to make it easier to understand
  args.verbose = int(args.verbose) - 1
  try:
    # set logging level from command line arg.
    logger.setLevel(verb[(args.verbose)])
  except:
    # if out of range use levels, and account for standard levels
    if (args.verbose - 2) > 0:
      logger.setLevel(logging.DEBUG - (args.verbose - 2))
    else:
      logger.setLevel(logging.DEBUG)

  logger.info('Starting script ' + os.path.join(os.path.dirname(os.path.realpath(__file__)), __file__))
  logger.info('config file = ' + args.config)
  logger.info('ws281x file handle = ' + args.ws281x)
  logger.info('POST Delays = ' + str(args.postDelay) + " seconds")

  # log which levels of debug are enabled.
  logger.log(logging.DEBUG-9, "discrete log level = " + str(logging.DEBUG-9))
  logger.log(logging.DEBUG-8, "discrete log level = " + str(logging.DEBUG-8))
  logger.log(logging.DEBUG-7, "discrete log level = " + str(logging.DEBUG-7))
  logger.log(logging.DEBUG-6, "discrete log level = " + str(logging.DEBUG-6))
  logger.log(logging.DEBUG-5, "discrete log level = " + str(logging.DEBUG-5))
  logger.log(logging.DEBUG-4, "discrete log level = " + str(logging.DEBUG-4))
  logger.log(logging.DEBUG-3, "discrete log level = " + str(logging.DEBUG-3))
  logger.log(logging.DEBUG-2, "discrete log level = " + str(logging.DEBUG-2))
  logger.log(logging.DEBUG-1, "discrete log level = " + str(logging.DEBUG-1))
  logger.log(logging.DEBUG,   "discrete log level = " + str(logging.DEBUG  ))
  logger.info('verbose = ' + str(args.verbose) + ", logger level = " + str(logger.getEffectiveLevel()))
  logger.debug('debug level enabled')
  logger.info('info  level enabled')
  #logger.warn(u'warn  level enabled')
  #logger.error(u'error  level enabled')
  #logger.critical(u'critical  level enabled')

  # extra levels of DEBUG of configuration file.
  logger.log(logging.DEBUG-1, "list of config sections = \r\n" + pp.pformat(list(config.keys())))
  first_section_key = list(config.keys())[0]
  logger.log(logging.DEBUG-2, "first section name = " + pp.pformat(first_section_key))
  first_section_dict = config[first_section_key]
  logger.log(logging.DEBUG-3, "list of first sections items = \r\n" + pp.pformat(first_section_dict))
  first_sections_first_item = list(first_section_dict.keys())[0]
  logger.log(logging.DEBUG-4, "config["+first_section_key+"]["+first_sections_first_item+"] = " + config[first_section_key][first_sections_first_item])
  logger.log(logging.DEBUG-5, "config = " + pp.pformat(config))
# end of setupLogging():

def write_ws281x(cmd):
  with open(args.ws281x, 'w') as the_file:
    logger.debug("ws281x cmd: " + cmd.replace("\n", "\\n"))
    the_file.write(cmd)
    # file closes with unindent.
    # close needed for ws2812svr to process file handle
# end of write_ws281x():

def signal_handler(signal, frame):
  # handle ctrl+c gracefully
  logger.info("CTRL+C Exit LED test of ALL off")
  write_ws281x('fill ' + str(ws281xPWMchannel) + ',' + colors['off'] + '\nrender\n')

  logger.info('Exiting script ' + os.path.join(os.path.dirname(os.path.realpath(__file__)), __file__))

  sys.exit(0)
# end of signal_handler():

main()
