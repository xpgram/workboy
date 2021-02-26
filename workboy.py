from datetime import date
from datetime import datetime
import textwrap
import shlex
import json
import os
import sys
import re

# TODO All ID dictionaries should have their ID space compressed on save.
# Rather, the working record should do so on save.

helpText = '''
workboy                     : Display recent activity.
workboy all                 : Displays the entire company index.
workboy recent              : Displays all log activities from the last 30 days.
workboy [name]              : Displays a company record by name or ID. Starts the edit-poller.
workboy add [name]          : Add a new company to the index. Starts the edit-poller.
workboy del [name]          : Deletes a company by name or ID from the index.
workboy once ...            : Prepend that ends continuous polling, treating this request as final.

Any command which starts edit-polling will pass the remaining arguments to the polling system.

Edit-Poller:
done/quit                   : Immediately ends polling and signals the program to save the index.
cancel                      : Immediately ends polling and closes the program without saving.
info [message]              : Adds a new string (must be in quotes) to the company detail.
contact [name/id] [details] : Adds a new or selects and edits an existing company representative.
log [date?] [message]       : Adds a new string (must be in quotes) to the interaction history.
                              Each of the special keywords 'info,' 'contact' and 'log' may be
                              followed by 'del' and an index number to select and remove an entry
                              from the list.
info move [idx] [insert idx]: Moves an existing message to a new place in the message order.
                              As a side effect, reassigns all message IDs by order as well.
rename [name]               : Changes the record's name.
                              To change the company's street address, url, phone number, etc.:
                              submit it into polling, the interpreter will figure out what it is
                              and update the record as such.

Archiving and data-restoration commands.

workboy always saves a copy of the previous data record before writing the current one, in
case of catastrophic data failure. workboy attempts to be smart about this, but it is still
possible to overwrite your data and your auto-backup data, so be careful.

workboy's archival functions are its best data failsafes: they cannot be overwritten as a
matter of workboy's typical operations. It is recommended to archive periodically and before
any changes to workboy's code.

workboy restore-backup          : Restores the last auto-backup to the current record.
workboy archive                 : Save a copy of the record as is under today's date.
workboy restore-archive [date]  : Restores an archive file to the current data record
                                  if the given date is valid.
workboy display-archives        : Prints all known archive files.
workboy delete-archive          : Deletes an archive file if the given date is valid.
'''.strip()


####################################################################################################
#### Support functions                                                                          ####
####################################################################################################

####################################################################################################
#### Regex strings and checkers

# Regex patterns
regexName = r'^[\w ,\.\-]+$'
regexURL = r'^w{3}\.[\w\-\.]+(\.\w{2,5}(\/[\w\-\.\/]*)?)$'                                  # generally incomplete, but sufficient.
regexPhoneNumber = r'^(\(?\d{3}\)?[ \-]?\d{3}[ \-]?\d{4})$'                                 # identifies 10 numbers in various grouping styles
regexStreetAddress = r'([\w\-\.]+, )?\w+, [A-Z]{2}( [\d\-]{5,})?$'                          # Matches "City, ST" with optional street and zipcode.
regexEmail = r'^([a-zA-Z0-9_\-\.]+)@([a-zA-Z0-9_\-\.]+)\.([a-zA-Z]{2,5})$'                  # standard email pattern
regexDate = r'^[a-zA-Z]{3} [0123]?\d(, (\d{2}|\d{4}))?$'                                    # normal format date (Jan 02, 2020)
regexDateShort = r'^[01]?\d-[0123]?\d(-(\d{2}|\d{4}))?$'                                    # short format date (1-2-20)

def regexCheck(pattern, string):
    "Returns True if the given string matches the given regex pattern."
    return re.search(pattern, string)


####################################################################################################
#### Dictionary and List convenience methods

def shift(a):
    "Returns the first value of array a and the remaining values as a new list, or None and [] if a was empty to begin with."
    v = a[0] if len(a) > 0 else None
    a = a[1:]
    return (v, a)

def get(i, a):
    "Returns the value held under index i of array a if one exists, returns None if not."
    return a[i] if i >= 0 and i < len(a) else None

def findKey(f, d):
    "Returns the key to dictionary d where f( d[k] ) returns True, returns None otherwise."
    results = [k for k, v in d.items() if f(v) == True]
    return results[0] if results else None

def stringToInt(s):
    "Converts a given string to a number, or returns None on failure."
    try:
        return int(s)
    except (ValueError, TypeError):
        return None

def destructure(dict, *keys):
    "Returns a list of values for the given keys in the order they appear as arguments to this function."
    return list(dict[key] for key in keys)


####################################################################################################
#### Date functions

def dateToString(d):
    "Converts a date object to a formatted string."
    return d.strftime('%b %d, %Y')

def dateFromString(s):
    "Converts a formatted string to a date object."
    return datetime.strptime(s, '%b %d, %Y').date()     # TODO Why datetime?

def parseDate(s):
    "Returns a date object parsed from a string s, or returns None if one couldn't be retrieved."
    result = None
    datePatterns = (
        '%b %d, %Y',
        '%b %d',
        '%Y-%m-%d',
        '%m-%d-%y',
        '%m-%d-%Y',
        '%m-%d'
        )
    for pattern in datePatterns:
        try:
            result = datetime.strptime(s, pattern).date()
            break
        except ValueError:
            pass
    if result != None:
        if result.year == 1900:     # Just assume a year wasn't provided; I got no relationship with 1900
            result = result.replace(year=date.today().year)
    return result


####################################################################################################
#### Other parsing functions

def parsePhoneNumber(s):
    "Extracts all numbers from a string and returns them as a string, or returns None if one couldn't be retrieved."
    nums = [ c for c in s if c.isdigit() ]
    return ''.join(nums) if 10 <= len(nums) <= 11 else None

def parseIDNumber(s, l=4):
    "Given a numerical string s, returns a zero-padded string of length l."
    assert str(s).isnumeric(), 'ID Numbers may only contain numerics. Given \'{}\''.format(s)
    return '{0:0>{1}}'.format(s, l)

####################################################################################################
#### Print functions                                                                            ####
####################################################################################################

statusDefunct = '[Defunct]'
statusResearching = 'Researching'
displayString = ['','']

def printBuffer(s=''):
    "'Prints' to an internal buffer string."
    displayString.insert(-1, s)

def displayBuffer():
    "Prints the internal buffer string to the console."
    global displayString
    if len(displayString) > 2:
        print('\n'.join(displayString))
    displayString = ['','']

def lineWrap(message, indent=0, width=98):
    "Wraps the given message to some character width limit, including a left-margin equal to indent."
    lines = textwrap.wrap(message, width-indent)    # returns [line1, line2, line3, ...]
    spacer = '\n{}'.format(' '*indent)
    return spacer.join(lines)

def formatContact(record, id):
    "Given a dictionary representing a personal contact, return a neatly readable string."
    name, primary, email, phone = destructure(record, 'name', 'primary', 'email', 'phone')

    # format → "##-[name]        (primary) | [email] | [phone]"
    fields = [
        '{:0>2}> '.format(id),
        '{:<20}'.format(name),
        '{:>10}'.format('(primary)' if primary else ''),
        ' | {}'.format(email) if email else '',
        ' | {}'.format(formatPhoneNumber(phone)) if phone else ''
    ]
    return ''.join(fields)

def formatInfo(message, idx):
    "Given an info string pertaining to some company, return a neatly readable string."
    # format → "00> [lots of text ...]"
    lead = '{:0>2}> '.format(idx)
    indent = len(lead)
    r = lead + lineWrap(message, indent)
    return r

def formatLog(log, idx):
    "Given a contact-log dictionary (a date and message pair), return a neatly readable string."
    # format → "00> Jan 01, 2020 : [lots of text ...]"
    lead = "{:0>2}> {:>12} : ".format(idx, log['date'])
    indent = len(lead)
    r = lead + lineWrap(log['message'], indent)
    return r

def formatPhoneNumber(s):
    "Given a 10-length string number (not enforced), return a neatly readable phone number."
    assert (10 <= len(s) <= 11), 'Legal phone numbers are between 10 and 11 digits.'

    tendigit = (len(s) == 10)
    lead = '' if tendigit else '{}-'.format(s[0])
    number = s if tendigit else s[1:]
    
    # format → "(0-000) 000-0000"
    return "({}{}) {}-{}".format(lead, number[0:3], number[3:6], number[6:])

def applicationStatus(company):
    "Given a dictionary of company information, returns a string representing the application status with them."
    if company['defunct']:
        return statusDefunct
    if not company['log']:
        return statusResearching
    # else
    datesList = list(company['log'].values())
    lastDate = dateFromString(datesList[-1]['date'])
    difference = date.today() - lastDate
    return '{} days'.format(difference.days)

def formatCompany(id, record):
    "Given a dictionary of company information, returns a neatly readable string."
    lines = []

    def addline(s):
        lines.append(s)

    name, url, phone, address, contacts, info, log = destructure(record, 'name', 'url', 'phone', 'address', 'contacts', 'info', 'log')

    # line 01 - ID + COMPANY + APPLICATION STATUS
    addline( "{} {} — {}".format(id, name, applicationStatus(record)) )

    # line 02 - URL + PHONE NUMBER
    line = [url, formatPhoneNumber(phone) if phone else '']
    line = list(filter(lambda msg: msg != '', line))
    addline( ' | '.join(line) ) if line else None

    # line 03 - STREET ADDRESS
    addline(address) if address else None

    # line 04 - PEOPLE
    addline('\nContacts:') if contacts else None
    for id, data in contacts.items():
        addline( formatContact(data, id) )

    # line 05 - INFO
    addline('\nInfo:') if info else None
    for id, msg in info.items():
        addline( formatInfo(msg, id) )

    # line 06 - CONTACT LOG
    addline('\nLog:') if log else None
    for id, msg in log.items():
        addline( formatLog(msg, id) )

    # send
    return '\n'.join(lines)

def formatCompanyShort(id, record):
    "Given a dictionary of information, prints a single line blurb about the application status of that company."
    status = applicationStatus(record)
    return '{} {:<40} | {}'.format(id, record['name'], status)


####################################################################################################
#### Dictionary Objects                                                                         ####
####################################################################################################

def newCompany(name=''):
    "Returns a new company dict"
    return {
        'name': name,           # company name
        'url': '',              # company website
        'phone': '',            # company phone number
        'address': '',          # street address
        'contacts': {},         # list of personal contacts within the company
        'info': {},             # list of itemized information strings
        'log': {},              # list of recorded interactions with this company: date + description of what happened
        'defunct': False        # whether application process is closed (failed)
    }

def newContact():
    "Returns a new contact dict."
    return {
        'name': '',
        'email': '',
        'phone': '',
        'primary': False
    }

def newLog():
    "Returns a new log-message dict."
    return {
        'date': dateToString(date.today()),
        'message': ''
    }


####################################################################################################
#### ID Managing Functions                                                                      ####
####################################################################################################

def newID(index, l=4):
    "Returns a length l string guaranteed to be a unique identifier in index."
    LIMIT = 10**l - 1               # get the maximum allowable index for the given string length
    id = len(index.keys()) - 1      # get last theoretical element-index of record
    openSpaceExists = id < LIMIT    # Confirm that the number of entries has not completely filled ID space.
    idstring = ''

    assert id < LIMIT, 'I think we\'re full, yo. Given record has {} elements.'.format(id)
    assert l > 0, 'What happened, dude? ID length has to be greater than 0.'

    while openSpaceExists:
        id = (id + 1) if id <= LIMIT else 0
        if (idstring := parseIDNumber(id, l)) not in index:
            break

    return idstring

def reduceSelectionToID(input, index, l=4):
    """Returns input either parsed and formatted to a valid ID key if numerical,
    or the ID to a record for which input is a matching string name."""
    op1 = lambda: parseIDNumber(input, l)
    op2 = lambda: findKey(lambda v: (v['name'].lower() if 'name' in v else None) == str(input).lower(), index)
    return op1() if input.isnumeric() else op2()

def IDDictionaryToList(dictionary):
    "Converts a dictionary of IDs to a list ordered by ID value."
    return [ v for k, v in sorted(dictionary.items(), key=lambda pair: pair[0]) ]

def listToIDDictionary(listValues, l=4):
    "Converts a list of values to an ID dictionary whose IDs are set in ascending order by occurrence."
    return { parseIDNumber(k, l=l): v for k, v in enumerate(listValues) }

def compressDictionaryIDSpace(dictionary):
    "Given a dictionary of IDs, reassigns IDs such that there are no gaps between 0 and len(dictionary)."
    l = len(dictionary.keys()[0]) if dictionary else 0
    a = IDDictionaryToList(dictionary)
    return listToIDDictionary(a, l)


####################################################################################################
#### Argument Processor Functions                                                               ####
####################################################################################################


# TODO Make this immutable? The last change toward functional design, I think. Not sure it's really worth it, though.
class InputProcessorState:
    "Represents the input-looper's state at any one instant."
    def __init__(self, index, args, command_set):
        self.index = index
        self.record = None
        self.recordKey = None
        self.args = args
        self.last = None
        self.command_set = command_set
        self.pollingEnabled = True
        self.exitSignal = False

    def shift(self):
        self.last, self.args = shift(self.args)
        return self.last

    def unshift(self):
        if self.last != None:
            self.args = [self.last] + self.args
            self.last = None

    def setRecord(self, id):
        if id in self.index:
            self.record = self.index[id]
            self.recordKey = id
        else:
            self.record = None
            self.recordKey = None

    def showRecord(self):
        if self.record:
            print( '\n'.join(['', formatCompany(self.recordKey, self.record), '']) )

    def clear(self):
        self.args = []

    def get(self, i):
        return get(i, self.args)

    def pollingRequested(self):
        "Returns True if this state desires user-input polling fill its arguments queue."
        return (not self.args) and self.record and self.pollingEnabled

def inputProcessor(state):
    "The 'game-loop,' if you will."
    # A do-until construction
    while True:
        if state.pollingRequested():
            try:
                state.args = shlex.split( input('> ') )
            except ValueError:
                print('Input was malformed. Try again.')

        # Execute command instruction and collect new state for next iteration.
        command = state.shift()
        state = state.command_set.switch(command)(state)
        assert type(state) == InputProcessorState, 'All input processor functions must return an input processor state.'

        # until clause
        if not (state.args or state.pollingRequested()):
            break

class Switcher:
    "Keyword switch-case framework for matching string commands to function calls."
    def __init__(self, dictionary, default):
        self.switcher = dictionary
        self.default = default

    def switch(self, key):
        return self.switcher.get(key, self.default)
        

####################################################################################################
#### Company Index Edit Mode

def displayHelpText(state):
    "Prints program usage instructions to the console."
    printBuffer(helpText)
    displayBuffer()
    return cancelChanges(state)

def displayRecents(state):
    "Display an at-a-glance look at any pending job applications."
    beingAppliedFor = lambda c: applicationStatus(c)[0].isdigit()
    beingResearched = lambda c: applicationStatus(c) == statusResearching

    # Reduce index to active applications
    applying    = { k:c for k, c in state.index.items() if beingAppliedFor(c) }
    researching = { k:c for k, c in state.index.items() if beingResearched(c) }

    printBuffer("Use 'workboy help' for more information.")
    printBuffer()

    # First, print in-progress applications
    for companyID in applying:                                            
        printBuffer( formatCompanyShort(companyID, applying[companyID]) )

    # Line break
    printBuffer() if applying and researching else None

    # Second, print unsent applications
    for companyID in researching:
        printBuffer( formatCompanyShort(companyID, researching[companyID]) )

    # If nothing was printed, tell the user why.
    if not applying and not researching:
        printBuffer('No active applications in index.')

    displayBuffer()
    
    return cancelChanges(state)

def displayAll(state):
    "Display an at-a-glance look at all job applications, past and present."

    for companyID in state.index:
        printBuffer( formatCompanyShort(companyID, state.index[companyID]) )
    if not state.index:
        printBuffer('Company index is empty. Nothing to show.')
    displayBuffer()

    return cancelChanges(state)

def displayRecentActivity(state):
    "Display logged activities from the last 30 days."

    today = date.today()
    activities = []

    # Collect all relevant logs from all company records
    for record in state.index.values():
        for log in record['log'].values():
            log = log.copy()
            log['company'] = record['name']
            log['dateEval'] = dateFromString(log['date'])
            if (today - log['dateEval']).days <= 30:
                activities.append(log)

    # Sort and print
    calendar = sorted(activities, key=lambda log: log['dateEval'])
    for log in calendar:
        ellipses = '...' if len(log['message']) > 70 else ''
        printBuffer('{:<20} > {} : {:<70}{}'.format(log['company'], log['date'], log['message'], ellipses))
    displayBuffer()

    return cancelChanges(state)

def addCompany(state):
    "Adds a new record to the company index. Assumes all input thereafter are company details."

    recordID = newID(state.index)
    name = state.shift()

    # Confirm that name is compliant.
    validName = name != '' and regexCheck(regexName, name)

    # Confirm that name is unique.
    names = [ v['name'].lower() for k, v in state.index.items() ]
    preexisting = name.lower() in names

    if not validName:
        print('\'{}\' does not fit the company-name field schema. Request was voided.'.format(name))
        state = endProcessing(state)

    if preexisting:
        print("'{}' already exists in the record. Request was voided.".format(name))
        state = endProcessing(state)

    else: # create new record and add to index
        record = newCompany()
        record['name'] = name

        state.index[recordID] = record
        state.setRecord(recordID)
        state.showRecord()
        state.command_set = companyRecordSet

    return state

def delCompany(state):
    "Deletes a record from the index, with user confirmation."

    key = state.shift()
    id = reduceSelectionToID(key, state.index)

    if not id or id not in state.index:
        printBuffer("Selection '{}' could not be found.".format(key))
        displayBuffer()

    else:
        # Inform the user of which record they are considering
        state.setRecord(id)
        state.showRecord()

        # Get confirmation from user.
        response = input('Are you sure?: ').lower()
        affirmativeResponses = ['y', 'yes']
        if response in affirmativeResponses:
            del state.index[id]
            print('Deleted.')

    return endProcessing(state)

def editModeOff(state):
    "Function-object wrapper for disabling user polling."
    state.pollingEnabled = False
    return state

def selectCompany(state):
    "With user input, determines which existing company record the user would like to work with and assigns it to state."

    # key is either a numeric ID or a name string; retrieve a company ID in any case.
    key = state.last
    id = reduceSelectionToID(key, state.index)

    if not id or id not in state.index:
        printBuffer('Selection \'{}\' could not be found.'.format(key))
        state = endProcessing(state)

    else:
        state.setRecord(id)
        state.showRecord()
        state.command_set = companyRecordSet

    displayBuffer()

    return state

def endProcessing(state):
    "Signals the input processor that it should save and close."
    state.pollingEnabled = False
    state.clear()
    return state

def cancelChanges(state):
    "Signals the input processor that it should close without saving."
    global saveOnExit
    saveOnExit = False
    return endProcessing(state)

globalRecordSet = Switcher({
    None: displayRecents,
    'all': displayAll,
    'recent': displayRecentActivity,
    'add': addCompany,
    'del': delCompany,
    'once': editModeOff,
    'help': displayHelpText
    },
    selectCompany
    )

####################################################################################################
#### Company Edit Mode

def nextLoopIteration(state):
    "Simply passes this input processor loop to the next. I.e., if polling is enabled, continue polling."
    return state

# TODO Move this somewhere appropriate.
def omitKeyValuePairFromCollection(collection, selection, printFunction, l=4):
    """Given a collection and a valid indice idx, returns a new collection minus the value held at idx.
    If the indice is not valid, simply returns the same collection."""

    newCollection = None
    record = None
    key = None
    success = False

    # collection is a dictionary using id-strings.
    if type(collection) == dict:
        key = reduceSelectionToID(selection, collection, l)
        newCollection = collection.copy()
        if key in collection:
            del newCollection[key]
            record = collection[key]
            success = True
    
    # collection is an enumerable (probably.. hopefully.)
    else:
        key = stringToInt(selection)
        if key != None:
            newCollection = collection[:key] + collection[key+1:]
            record = collection[key]
            success = True

    if not success:
        print("'{}' could not be found or is not a valid selection.".format(selection))
    else:
        print( printFunction(record, key) )
        print('Deleted.')

    return newCollection

def editInfo(state):
    "Adds a new message to the info-log, or deletes one if given 'del' and an indice to locate with."
    index = state.record['info']
    message = state.shift()

    if message == 'del':
        state.record['info'] = omitKeyValuePairFromCollection(index, state.shift(), formatInfo, l=2)
    elif message == 'move':
        a1, a2 = state.shift(), state.shift()

        if not (a1.isdigit() and a2.isdigit()):
            print("'info move [idx] [idx]' accepts two numbers: recieved {}, {}. Request voided.".format(a1, a2))
        else:
            id = parseIDNumber(a1, l=2)
            if id not in index:
                print("Message ID {} could not be found in the list.".format(id))
            else:
                msgList = IDDictionaryToList(index)
                msg = index[id]
                msgi = msgList.index(msg)
                newi = max(int(a2), 0)

                msgList.pop(msgi)
                msgList.insert(newi, msg)

                state.record['info'] = listToIDDictionary(msgList, l=2)
    else:
        id = newID(index, l=2)
        if id:
            state.record['info'][id] = message
        else:
            print('Could not add new message: info detail ID space is full.')

    state.clear()
    return state

def editContact(state):
    """Adds a new contact to the contact dictionary, edits one already present, or deletes one if given
    'del' and an indice to locate with."""
    key = state.shift()
    index = state.record['contacts']

    if key == 'del':
        state.record['contacts'] = omitKeyValuePairFromCollection(index, state.shift(), formatContact, l=2)
    else:
        id = reduceSelectionToID(key, index, l=2)
        contact = None

        if not id:
            contact = newContact()
            state.unshift() # Last token might be the name field
            id = newID(index, 2)
        else:
            contact = index[id]
        
        contact = editRecord(contact, state.args, iptrConfig_contact)
        
        state.record['contacts'][id] = contact
        
    state.clear()
    return state

def editLog(state):
    "Adds a new message to the event log or deletes one if given 'del' and an indice to locate with."
    command = state.shift()
    index = state.record['log']

    if command == 'del':
        state.record['log'] = omitKeyValuePairFromCollection(index, state.shift(), formatLog, l=2)
    
    else:
        state.unshift()
        id = newID(index, l=2)
        if id:
            log = editRecord(newLog(), state.args, iptrConfig_log)
            state.record['log'][id] = log
        else:
            print('Could not add new log: message ID space is full.')

        # sort by date, ascending; reassign indices, too.
        sortedList = sorted(index.items(), key=lambda i: dateFromString(i[1]['date']))
        state.record['log'] = { parseIDNumber(str(i), l=2): v[1] for i,v in enumerate(sortedList) }

    state.clear()
    return state

def editCompany(state):
    "Interprets the last user token as a company information field (street address, phone number, etc.)."
    state.unshift()

    state.record = editRecord(state.record, state.args, iptrConfig_company)
    state.index[state.recordKey] = state.record

    state.clear()
    return state

def renameCompany(state):
    "Changes the record's name field to the next given token."
    newName = state.shift()
    oldName = state.record['name']

    if regexCheck(regexName, newName):
        printBuffer('{} → {}'.format(oldName, newName))
        state.record['name'] = newName
    else:
        printBuffer("'{}' does not fit the company name schema. Name was not changed.".format(newName))
    displayBuffer()

    state.clear()
    return state

def printRecord(state):
    "Prints the complete company record to the console."
    state.showRecord()
    state.clear()
    return state

companyRecordSet = Switcher({
    None: nextLoopIteration,
    'info': editInfo,
    'contact': editContact,
    'log': editLog,
    'rename': renameCompany,
    'show': printRecord,
    'done': endProcessing,
    'quit': endProcessing,
    'cancel': cancelChanges
    },
    editCompany
    )


####################################################################################################
#### Argument Interpretation functions                                                          ####
####################################################################################################

class InterpreterConfig:
    "A config object for interpretArgument()."
    name = False
    url = False
    phone = False
    address = False
    email = False
    date = False
    message = False

# A config object for company objects
iptrConfig_company = InterpreterConfig()
iptrConfig_company.url = True
iptrConfig_company.phone = True
iptrConfig_company.address = True

# A config object for personal-contact objects
iptrConfig_contact = InterpreterConfig()
iptrConfig_contact.name = True
iptrConfig_contact.phone = True
iptrConfig_contact.email = True

# A config object for contact-log objects
iptrConfig_log = InterpreterConfig()
iptrConfig_log.date = True
iptrConfig_log.message = True

def interpretArgument(s, d, config):
    """Given a string argument s, interpret the kind of information it contains and set it to dictionary
    d, so long as the given config allows it."""
    success = True

    # Error message shorthand
    def invalidFieldMessage(s):
        print('Argument of type \'{}\' not valid for this record type.'.format(s))
        nonlocal success
        success = False

    # s is a date string
    if regexCheck(regexDate, s) or regexCheck(regexDateShort, s):
        if config.date:
            date = parseDate(s)
            if date:
                d['date'] = date.strftime('%b %d, %Y')
            else:
                print('Recognized date string, but could not extract date object.')
        else:
            invalidFieldMessage('date')

    # s is an email string
    elif regexCheck(regexEmail, s):
        if config.email:
            d['email'] = s
        else:
            invalidFieldMessage('email')

    # s is a phone-number string
    elif regexCheck(regexPhoneNumber, s):
        if config.phone:
            d['phone'] = parsePhoneNumber(s)
        else:
            invalidFieldMessage('phone number')
    
    # s is a street address
    elif regexCheck(regexStreetAddress, s):
        if config.address:
            d['address'] = s
        else:
            invalidFieldMessage('address')

    # s is a url
    elif regexCheck(regexURL, s):
        if config.url:
            d['url'] = s
        else:
            invalidFieldMessage('web url')

    # s is a name
    elif regexCheck(regexName, s) and config.name:
        d['name'] = s

    # s is a string message — default condition if 'message' is allowed
    elif config.message:
        d['message'] = s

    # default condition — s could not be interpreted.
    else:
        print('Could not interpret input \'{}\'.'.format(s))
        success = False

    return success

def deleteInformationField(s, dictionary):
    "Given a string, attempts to delete the described information type from a given dictionary."

    fieldType = s.lower()

    blankValue = ''
    # Special erase conditions
    dictTypes = ['contacts','info','log']
    if s in dictTypes:
        blankValue = {}
    elif s == 'defunct':
        blankValue = False

    if fieldType in dictionary:
        dictionary[fieldType] = blankValue
        return True
    else:
        return False


####################################################################################################
#### Record functions                                                                           ####
####################################################################################################

def editRecord(record, args, config):
    """Returns an edited, shallow-copy of given dict 'record' via the list of arguments 'args'
    with respect to the given config settings."""

    new_record = record.copy()
    deleteMode = False

    for arg in args:
        # Purely for contacts — lets '-p' toggle the primary flag
        if arg.lower() == '-p' and 'primary' in new_record:
            new_record['primary'] = False if deleteMode else not new_record['primary']
            continue

        # Purely for company records — lets 'defunct' toggle the 'closed application' flag
        if arg.lower() == 'defunct' and 'defunct' in new_record:
            new_record['defunct'] = False if deleteMode else not new_record['defunct']
            continue

        # Delete-field toggle
        if arg == 'del' or arg == 'add':
            deleteMode = (arg == 'del')
            continue

        # Edit/Delete information-field control pass
        if not deleteMode:
            interpretArgument(arg, new_record, config)
        else:
            deleteInformationField(arg, new_record)

    return new_record


####################################################################################################
#### Script Variables                                                                           ####
####################################################################################################

# File path constants
datafolderPath = '%LOCALAPPDATA%\\workboy'
datafolderPath = os.path.expandvars(datafolderPath)
datafilePath = datafolderPath + '\\workboy_data'
backupfilePath = datafolderPath + '\\workboy_backup'
archivefilePath = datafolderPath + '\\workboy_archive' + str(date.today())

saveOnExit = True               # Whether to save the contents of the company index on exiting the program.
backupSaveData = ''             # The datafile as a single string. Used to save a backup copy on program exit.

companyIndex = {}               # Global index of saved company records. By default, empty.

argv = sys.argv[1:]             # Shorthand for script arguments. Discards first since it is always 'workboy'


####################################################################################################
#### Open Script                                                                                ####
####################################################################################################

# Try to make the datafile directory if it does not exist
try:
    os.mkdir(datafolderPath)
except OSError:
    pass

# Restore backed-up old datafile if told to
if get(0, argv) == 'restore-backup':
    try:
        with open(backupfilePath, 'r') as backup:
            with open(datafilePath, 'w') as datafile:
                save = backup.read()
                datafile.write(save)
        print('Backup data restored.')
    except FileNotFoundError:
        print('Failed: no backup file exists for workboy.')
    finally:
        exit()  # Force quit script

# Archive current record
if get(0, argv) == 'archive':
    try:
        with open(datafilePath, 'r') as datafile:
            with open(archivefilePath, 'w') as archivefile:
                save = datafile.read()
                archivefile.write(save)
        print("History archived at:")
        print("    " + archivefilePath)
    except FileNotFoundError:
        print('Failed: no record to archive.')
    finally:
        exit()  # Force quite script

# Restore archive from specified date
if get(0, argv) == 'restore-archive':
    dateStr = dateStr if (dateStr := get(1, argv)) != None else ''
    when = parseDate(dateStr)

    if when == None:
        print('Date input was malformed or did not exist. Could not identify which archive date to process.')
        exit()
    
    try:
        targetPath = datafolderPath + '\\workboy_archive' + str(when)
        with open(targetPath, 'r') as archivefile:
            with open(datafilePath, 'w') as datafile:
                save = archivefile.read()
                datafile.write(save)
        print('Archive restored.')
    except FileNotFoundError:
        print('Failed: no archive from date "{}" exists.'.format(when))
    finally:
        exit()

# Print archive files.
if get(0, argv) == 'display-archives':
    files = [f for f in os.listdir(datafolderPath) if os.path.isfile(os.path.join(datafolderPath, f))]
    files = [f for f in files if f not in ["workboy_data", "workboy_backup"]]

    pre = "Held archives:\n" if len(files) > 0 else "No archived records."
    printBuffer(pre)
    for f in files:
        printBuffer(f)

    displayBuffer()
    exit()

# Delete an archive file.
if get(0, argv) == 'delete-archive':
    dateStr = dateStr if (dateStr := get(1, argv)) != None else ''
    when = parseDate(dateStr)

    if when == None:
        print('Date input was malformed or did not exist. Could not identify which archive data to delete.')
        exit()

    try:
        targetPath = datafolderPath + '\\workboy_archive' + str(when)
        os.remove(targetPath)
        print('Archive removed.')
    except FileNotFoundError:
        print('Failed: no archive from date "{}" exists.'.format(when))
    finally:
        exit()

    exit()

# Open and read the datafile, if it exists
try:
    with open(datafilePath, 'r') as datafile:
        string = datafile.read()
        if string.strip():
            companyIndex = json.loads(string)
            backupSaveData = string
except FileNotFoundError:
    pass    # Nothing to read here — use default, empty companyIndex
except json.decoder.JSONDecodeError as e:
    print(e)
    print('Failed: datafile for workboy exists, but could not be read')
    exit()  # Force quit script


####################################################################################################
#### Script Command Interpreter                                                                 ####
####################################################################################################

processorState = InputProcessorState(companyIndex, argv, globalRecordSet)
inputProcessor(processorState)


####################################################################################################
#### Close Script                                                                               ####
####################################################################################################

# Save the program and backup the old data collected before program execution.
# saveOnExit = False
if saveOnExit:
    with open(backupfilePath, 'w') as backup:   # Save the last-known-working-copy of the datafile
        backup.write(backupSaveData)
    with open(datafilePath, 'w') as datafile:   # 
        save = json.dumps(companyIndex)
        datafile.write(save)