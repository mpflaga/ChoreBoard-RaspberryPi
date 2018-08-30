#!/usr/bin/env python3

# python standard libraries
import __main__, sys, os, signal, pprint, configparser, argparse, logging, logging.handlers, time, random, copy, geocoder
from crontab import CronTab
from datetime import datetime, timedelta, date
from time import time, sleep, localtime, mktime, strptime
from astral import Location

# Raspberry Pi specific libraries
import pigpio


#### Global Variables ####

# ws2812svr constants
ws281x = { 'PWMchannel' : 2,
           'NeopixelPin' : 13,
           'Brightness' : int(255/4),
           'Invert' : 0,
           'LedCount' : 0, # will be calculated later, from the INI file
           'LedType' : 1
         }

colors = { 'off' : '000000',
           'red' : 'FF0000',
           'grn' : '00FF00',
           'green' : '00FF00',
           'blu' : '0000FF',
           'blue' : '0000FF',
           'ylw' : 'FFFF00',
           'yellow' : 'FFFF00',
           'brw' : '7F2805',
           'brown' : '7F2805',
           'prp' : 'B54A8F',
           'purple' : 'B54A8F',
           'wht' : 'FFFFFF',
           'white' : 'FFFFFF'
         }

pp = pprint.PrettyPrinter(indent=4) # Setup format for pprint.
fn = os.path.splitext(os.path.basename(__main__.__file__))[0]
args = None
config = None
tasks = None

def cbf_button(GPIO, level, tick):
  global tasks
  
  currentDate = datetime.now()
  logger.debug('gpio_pin = ' + str(GPIO ) + ', level = ' + str(level ) + ', tick "' + str(tick) + ', currentDate = ' + str(currentDate))
  for section in tasks.keys():
    if int(tasks[section]['gpio_pin']) == GPIO:
      ''' if GPIO is a defined task lets record the button change '''
      if level == 0 :
        ''' if button was pressed '''
        buttonAction = 'ButtonPresses'
        color = colors['wht']
      else:
        '''  otherwise it was released '''
        buttonAction = 'ButtonReleases'
        color = colors[tasks[section]['currentColor']]
          
      logger.log(logging.DEBUG-1, "tasks["+section+"] button = "+buttonAction)
      if (tasks[section]['PendingGraceDate'] < currentDate <= tasks[section]['PendingToLateDate']) or args.lightbutton :
        ''' Only update if task is in time window '''
        tasks[section][buttonAction].append(currentDate)
        tasks[section][buttonAction] = tasks[section][buttonAction][-4:] # truncate to only recent changes.
        if tasks[section].get('description'):
          logger.log(logging.DEBUG-1, "tasks["+section+"]['description'] = " + tasks[section]['description'] )
        logger.log(logging.DEBUG-1, "tasks["+section+"]["+buttonAction+"] = " + str(tasks[section][buttonAction][-1]) )
        logger.log(logging.DEBUG-4, "tasks["+section+"]["+buttonAction+"] = " + pp.pformat(tasks[section][buttonAction]) )

      if ((tasks[section]['PendingGraceDate'] < currentDate <= tasks[section]['PendingToLateDate']) or (buttonAction == 'ButtonReleases') or args.lightbutton ) :
        ''' Only update if task is in time window or if restoring color to avoid timing hole of being left on.'''
        write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + \
                     color  + ',' + \
                     str(tasks[section]['led_start']) + ',' + \
                     str(int(tasks[section]['led_length'])) + \
                     '\nrender\n')

def getNextDeadLine(currentDate, section):
  PendingDueDate = currentDate + timedelta(seconds = section['crontab'].next(currentDate.timestamp())) # Crontab.next() returns remaining seconds.
  logger.log(logging.DEBUG-2, 'New PendingDueDate = ' + PendingDueDate.strftime('%Y-%m-%d %a %H:%M:%S'))

  if ':' in section['grace']:
    x = strptime(section['grace'],'%H:%M:%S')
    grace_sec = timedelta(hours=x.tm_hour,minutes=x.tm_min,seconds=x.tm_sec).total_seconds()
  else:
    grace_sec = int(section['grace'])
  PendingGraceDate = PendingDueDate - timedelta(seconds = grace_sec) # Time to Start Yellow LEDs
  logger.log(logging.DEBUG-2, 'New PendingGraceDate = ' + PendingGraceDate.strftime('%Y-%m-%d %a %H:%M:%S'))
  
  if ':' in section['persist']:
    x = strptime(section['persist'],'%H:%M:%S')
    persist_sec = timedelta(hours=x.tm_hour,minutes=x.tm_min,seconds=x.tm_sec).total_seconds()
  else:
    persist_sec = int(section['persist'])
  PendingToLateDate = PendingDueDate + timedelta(seconds = persist_sec) # delay until turn off LEDs
  logger.log(logging.DEBUG-2, 'New PendingGraceDate = ' + PendingGraceDate.strftime('%Y-%m-%d %a %H:%M:%S'))

  return PendingDueDate, PendingGraceDate, PendingToLateDate

def main():
  global ws281x
  global tasks

  ParseArgs()
  setupLogging()

  # initialize CTRL-C Exit handler
  signal.signal(signal.SIGINT, signal_handler)


  # and determine maximum LED position
  ws281x['LedCount'] = 0
  buttonPins = {}
  tasks = {}
  
  currentDate = datetime.now()

  ''' Initially determine and adjust for current Day or Night Time Mode of LED brightness '''
  config['Title 0']['dawn'], config['Title 0']['sunset'] = getSunUPandSunDown()
  if currentDate < config['Title 0']['dawn'] :
    ''' Morning Mode '''
    logger.info('start the LEDs dimmed for morning')
    ws281x['Brightness'] = config['Title 0']['nightbrightness']
  elif config['Title 0']['dawn'] < currentDate < config['Title 0']['sunset'] :
    ''' Day Mode '''
    logger.info('start the LEDs at day time brightness')
    ws281x['Brightness'] = config['Title 0']['brightness']
  else :
    ''' Night Mode '''
    logger.info('start the LEDs dimmed for night time')
    ws281x['Brightness'] = config['Title 0']['nightbrightness']

  write_ws281x('brightness ' + str(ws281x['PWMchannel']) + ',' + \
     ws281x['Brightness'] + \
     '\nrender\n')
  
  logger.log(logging.DEBUG-2, 'config["Title 0"] = ' + pp.pformat(config['Title 0']))
  
  currentDate = datetime.now()
  for section in config.keys():
    if 'led_start' in config[section]:
      maxTemp = int(config[section]['led_start']) + int(config[section]['led_length'])
      if maxTemp > ws281x['LedCount']:
        ws281x['LedCount'] = maxTemp
    
    logger.debug("section = " + section + \
                 ", led_start = " + config[section]['led_start'] if 'led_start' in config[section] else "" + \
                 ", gpio_pin = " + config[section]['gpio_pin'] if 'gpio_pin' in config[section] else "" + \
                 (", led_length = " + config[section]['led_length']  + \
                 ", ws281x['LedCount'] = " + str(ws281x['LedCount']-1)) if 'led_length' in config[section] else "" + \
                 ', deadline = "' + config[section]['deadline'] + '"' if 'deadline' in config[section] else "" \
                 )

    if 'gpio_pin' in config[section]:
      if config[section]['gpio_pin'].isdigit() and ('deadline' in config[section]):

        ''' set glitch filter level either from last GPIO or Title or argument '''
        if 'glitch' in config[section].keys(): # if found in section
          glitch = int(config[section]['glitch']) # then go with it.
        elif 'glitch' in config['Title 0'].keys(): # if found in Title 0
          glitch = int(config['Title 0']['glitch'])
        else:
          glitch = int(args.glitch) # default
        buttonPins[int(config[section]['gpio_pin'])] = glitch
        tasks[section] = config[section]
        tasks[section]['crontab'] = CronTab(tasks[section]['deadline'])
        tasks[section]['PendingDueDate'], tasks[section]['PendingGraceDate'], tasks[section]['PendingToLateDate'] = getNextDeadLine(currentDate, tasks[section])
        tasks[section]['currentColor'] = 'off'
        tasks[section]['ButtonReleases'] = [currentDate]
        tasks[section]['ButtonPresses'] = [currentDate]
        tasks[section]['state'] = None
      
  logger.log(logging.DEBUG-4, "list of tasks = \r\n" + pp.pformat(list(tasks.keys())))
  logger.log(logging.DEBUG-5, "tasks = \r\n" + pp.pformat(tasks))

  logger.debug("Max LED position found to be " + str(ws281x['LedCount'] - 1))
  logger.debug("dict of pins = " + pp.pformat(buttonPins))

  #### POST - Neopixel Pre Operating Self Tests ####
  logger.debug("initializing ws2812svr")
  
  write_ws281x('setup {0},{1},{2},{3},{4},{5}\ninit\n'.format(ws281x['PWMchannel'], ws281x['LedCount'], ws281x['LedType'], ws281x['Invert'], ws281x['Brightness'], ws281x['NeopixelPin']))
  for colorName in ['red', 'grn', 'blu', 'off']:
    logger.debug("POST LED test of ALL " + colorName)
    write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + colors[colorName] + '\nrender\n')
    sleep(args.postDelay)

  config['Title 0']['currentColor'] = 'wht'
  write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + \
               colors[config['Title 0']['currentColor']]  + ',' + \
               str(config['Title 0']['led_start']) + ',' + \
               str(int(config['Title 0']['led_length'])) + \
               '\nrender\n')
  sleep(args.postDelay)
  write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + \
               colors['off']  + ',' + \
               str(config['Title 0']['led_start']) + ',' + \
               str(int(config['Title 0']['led_length'])) + \
               '\nrender\n')

  #### used to locate LEDs on device
  if args.walkLED:
    walk_leds()

  #### stop if command line requested.
  if args.stop :
    logger.info('Option set to just initialize and then quit')
    quit()

  #### halt if command line requested pause on fill of color.
  if args.haltOnColor :
    logger.info('Option set to just stay all ' + args.haltOnColor)
    if args.haltOnColor.lower() == 'rainbow' :
      write_ws281x('rainbow ' + str(ws281x['PWMchannel']) + '\nrender\n')
    elif args.haltOnColor.lower() == 'stickers' :
      palete = ['red', 'grn', 'blu', 'ylw', 'brw', 'prp', 'wht']
      for section in tasks.keys():
        write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + \
                     colors[palete[0]]  + ',' + \
                     str(tasks[section]['led_start']) + ',' + \
                     str(int(tasks[section]['led_length'])) + \
                     '\nrender\n')
        palete = ([palete[-1]] + palete[0:-1])
    else:
      write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + colors[args.haltOnColor] + '\nrender\n')
    logger.info('pausing on haltOnColor')
    while True:
      pass
    pi.stop()
    quit()

  pi = pigpio.pi()
  if not pi.connected:
     exit()

  cb = []
  for buttonPin in buttonPins:
    ''' config each used GPIO pins '''
    pi.set_mode(buttonPin, pigpio.INPUT)
    pi.set_pull_up_down(buttonPin, pigpio.PUD_UP)
    pi.set_glitch_filter(buttonPin, buttonPins[buttonPin])
    cb.append(pi.callback(buttonPin, pigpio.EITHER_EDGE, cbf_button))

  #### Main Loop
  try:
    while True:
      currentDate = datetime.now()

      ''' Determine and or adjust for change in Day or Night Time Mode of LED brightness '''
      if config['Title 0']['dawn'] < currentDate <= config['Title 0']['sunset']:
        ''' if we have ran thru the dawn then change to Day Time Mode and get next dawn '''
        logger.info('Time to brighten the LEDs')
        config['Title 0']['dawn'], _ = getSunUPandSunDown(date.today() + timedelta(days = 1)) # get next dawn
        logger.log(logging.DEBUG-2, 'config["Title 0"] = ' + pp.pformat(config['Title 0']))
        ws281x['Brightness'] = config['Title 0']['brightness']
        write_ws281x('brightness ' + str(ws281x['PWMchannel']) + ',' + \
             ws281x['Brightness'] + \
             '\nrender\n')
      elif config['Title 0']['sunset'] < currentDate :
        ''' if we have ran thru the sunset then change to Day Time Mode and get sunset dawn '''
        logger.info('Time to dim the LEDs')
        config['Title 0']['dawn'], config['Title 0']['sunset'] = getSunUPandSunDown(date.today() + timedelta(days = 1)) # get next sunset
        logger.log(logging.DEBUG-2, 'config["Title 0"] = ' + pp.pformat(config['Title 0']))
        ws281x['Brightness'] = config['Title 0']['nightbrightness']
        write_ws281x('brightness ' + str(ws281x['PWMchannel']) + ',' + \
             ws281x['Brightness'] + \
             '\nrender\n')
      
      ''' Check for Button Changes '''
      for section in tasks.keys():
        if tasks[section]['gpio_pin'].isdigit():

          ''' determine new state if needed '''
          priorState = tasks[section]['state']
          if ((currentDate <= tasks[section]['PendingGraceDate']) and (tasks[section]['state'] != 'beforeGrace')):
            ''' is it before the start of grace period, aka not yet expected to be started '''
            tasks[section]['state'] = 'beforeGrace'
          elif ((tasks[section]['PendingGraceDate'] < tasks[section]['ButtonReleases'][-1] <= tasks[section]['PendingToLateDate']) and (tasks[section]['state'] != 'completed')):
            ''' is it between start of Grace and End of TO Late, aka is not completed '''
            tasks[section]['state'] = 'completed'
          elif ((tasks[section]['PendingGraceDate'] < currentDate <= tasks[section]['PendingDueDate']) and not (tasks[section]['state'] in ['completed', 'pending'])) :
            ''' is it between start of Grace and Expected Dead Line, aka was it completed On Time '''
            tasks[section]['state'] = 'pending'
          elif ((tasks[section]['PendingDueDate'] < currentDate <= tasks[section]['PendingToLateDate']) and not (tasks[section]['state'] in ['completed', 'late'])) :
            ''' is it before Expected Dead Line, aka was it completed late '''
            tasks[section]['state'] = 'late'
          elif (tasks[section]['PendingToLateDate'] < currentDate) and tasks[section]['state'] != 'off':
            ''' if after deadline and if not off then turn off and set new deadlines, aka is it just over '''
            tasks[section]['state'] = 'off'
            tasks[section]['PendingDueDate'], tasks[section]['PendingGraceDate'], tasks[section]['PendingToLateDate'] = getNextDeadLine(currentDate, tasks[section])
          else: 
            ''' no state change '''
            pass 
          
          ''' log state change and determine new deadlines if needed '''
          if priorState != tasks[section]['state']:
            logger.debug('tasks[' + section + '] Changing state from ' + str(priorState) + ' to ' + tasks[section]['state'])

          ''' check if button is not being depressed '''
          if (pi.read(int(tasks[section]['gpio_pin'])) != 0) :
            ''' determine new color if needed '''
            priorColor = tasks[section]['currentColor']
            if tasks[section]['state'] in ['off', 'beforeGrace'] and priorColor != 'off':
              tasks[section]['currentColor'] = 'off'

            elif tasks[section]['state'] == 'pending' and priorColor != 'ylw' :
              tasks[section]['currentColor'] = 'ylw'

            elif tasks[section]['state'] == 'late' and priorColor != 'red':
              tasks[section]['currentColor'] = 'red'

            elif tasks[section]['state'] == 'completed' and priorColor != 'grn':
              tasks[section]['currentColor'] = 'grn'

            ''' update LED if color change '''
            if priorColor != tasks[section]['currentColor']:
              logger.log(logging.DEBUG-4, "tasks["+section+"] = " + pp.pformat(tasks[section]) )
              write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + \
                           colors[tasks[section]['currentColor']]  + ',' + \
                           str(tasks[section]['led_start']) + ',' + \
                           str(int(tasks[section]['led_length'])) + \
                           '\nrender\n')
                           
      sleep(1)

  except KeyboardInterrupt:
     print("\nTidying up")
     for c in cb:
        c.cancel()
  pi.stop()

#end of main():

def getSunUPandSunDown(when = datetime.now()):

  # geolocate dawn and sunset
  try:
    g = geocoder.ip('me')
    logger.log(logging.DEBUG-3, 'Geolocation found = ' + pp.pformat(g.lat))
    logger.log(logging.DEBUG-3, 'Geolocation found : lat=' + str(g.lat) + ' lng=' + str(g.lng))
    l = Location()
    l.latitude = g.lat
    l.longitude = g.lng
    l.timezone = 'US/Eastern'
    dawn = l.sun(when)['dawn'].replace(tzinfo=None)
    sunset = l.sun(when)['sunset'].replace(tzinfo=None)
    logger.log(logging.DEBUG-3, 'Todays dawn = ' + pp.pformat(dawn))
    logger.log(logging.DEBUG-3, 'Todays sunset = ' + pp.pformat(sunset))
    return dawn, sunset
  except:
    return None, None

def walk_leds():
  '''repo and manual is located at https://github.com/tom-2015/rpi-ws2812-server'''
  global ws281x
  for pos in range(ws281x['LedCount']):
    write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + \
                           colors['red']  + ',' + \
                           str(pos) + ',' + \
                           '1' + \
                           '\nrender\n')
    logger.debug('LED Index = ' + str(pos))

    try:
        eval(input("Press enter to continue"))
    except SyntaxError:
        pass

    write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + colors['off'] + '\nrender\n')
    pos = pos + 1
  exit()

def ParseArgs():
  global args
  global config
  global fn
  global ws281x

  # Get filename of running script without path and or extension.

  # Define command line arguments
  parser = argparse.ArgumentParser(description='Raspberry Pi MegaOperation board game.')
  parser.add_argument('--verbose', '-v', action='count', help='verbose multi level', default=1)
  parser.add_argument('--config', '-c', help='specify config file', default=(os.path.join(os.path.dirname(os.path.realpath(__file__)), fn + ".ini")))
  parser.add_argument('--io', help='specify pin and led file', default=(os.path.join(os.path.dirname(os.path.realpath(__file__)), fn + ".io")))
  parser.add_argument('--ws281x', '-w', help='specify ws281x file handle', default="/dev/ws281x")
  parser.add_argument('--brightness', '-b', help='specify intensity for ws281x 0-255 (off/full) after sunrise')
  parser.add_argument('--nightbrightness', '-n', help='same as brightness for after sunset')
  parser.add_argument('--timezone', '-z', help='specify local timezone, default is US/Eastern')
  parser.add_argument('--stop', '-s', action='store_true', help='just initialize and stop')
  parser.add_argument('--lightbutton', '-u', action='store_true', help='illuminate buttons when pressed')
  parser.add_argument('--haltOnColor', '-a', help='specify [color], "rainbow" or "sticker" to pause on. Recommend having dim brightenss')
  parser.add_argument('--postDelay', '-p', help='specify the LED delays at startup, in seconds', type=float, default="0.25")
  parser.add_argument('--walkLED', '-L', action='store_true', help='move LED increamentally, with standard input, used for determining LED positions.')
  parser.add_argument('--glitch', '-g', help='debounce period in ms for GPIO', default=100)

  # Read in and parse the command line arguments
  args = parser.parse_args()

  os.path.join(os.path.dirname(os.path.realpath(__file__)), args.config)
  os.path.join(os.path.dirname(os.path.realpath(__file__)), args.io)

  # Read in configuration file and create dictionary object
  configParse = configparser.ConfigParser()
  configParse.read(args.config)
  if os.path.exists(args.io): # read in IO pin defintions if in another file
    configParse.read(args.io)
  config = {s:dict(configParse.items(s)) for s in configParse.sections()} # convert object to dictionary.

  if args.brightness is not None:
    ws281x['Brightness'] = args.brightness
  elif 'brightness' in config['Title 0'].keys():
    ws281x['Brightness'] = config['Title 0']['brightness']
  assert 0 < int(ws281x['Brightness']) < 256

  if args.timezone is not None:
    config['Title 0']['timezone'] = args.timezone
  elif 'timezone' not in config['Title 0'].keys():
    config['Title 0']['timezone'] = 'US/Eastern'
  
  if args.nightbrightness is not None:
    config['Title 0']['nightbrightness'] = args.nightbrightness
  elif 'nightbrightness' not in config['Title 0'].keys():
    config['Title 0']['nightbrightness'] = '10'

# end of ParseArgs():

logger = None
def setupLogging():
  global args
  global config
  global fn
  global logger

  # Setup display and file logging with level support.
  logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-7.7s] (%(funcName)s) %(message)s")
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
    logger.log(logging.DEBUG-1, cmd.replace("\n", "\\n"))
    the_file.write(cmd)
    # file closes with unindent.
    # close needed for ws2812svr to process file handle
# end of write_ws281x():

def signal_handler(signal, frame):
  # handle ctrl+c gracefully
  logger.info("CTRL+C Exit LED test of ALL off")
  write_ws281x('fill ' + str(ws281x['PWMchannel']) + ',' + colors['off'] + '\nrender\n')

  logger.info('Exiting script ' + os.path.join(os.path.dirname(os.path.realpath(__file__)), __file__))

  sys.exit(0)
# end of signal_handler():

main()
