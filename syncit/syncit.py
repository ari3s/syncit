"""
syncit

The script gets data from the particular source and copies the data in Google
spreadsheet as it is defined in the config file.
"""
import argparse
import pyperclip

import numpy
import pandas as pd
import syncit.logger as log

from syncit.config import Config
from syncit.bzilla import Bzilla
from syncit.jira import Jira
from syncit.gsheet import Gsheet
from syncit.source import SourceData
from syncit.xsheet import Xsheet

CONFIG_FILE = 'syncit.yaml'

# Debug messages:
SCRIPT_FINISHED = 'script finished'
SCRIPT_STARTED = 'script started'

# Warning messages:
NOT_AVAILABLE = ': data update from input is not available in Google sheet '

# Info messages:
NO_UPDATE_MODE = 'no update mode (Google spreadsheet update is disabled)'

# Error messages:
UNKNOWN_SHEET = 'uknown sheet: '
UNKNOWN_SOURCE = 'unknown source'
UNKNOWN_KEY = 'unknown key in the sheet '

def get_cli_parameters():
    """ Get parameters from CLI and check that they are correct """
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, default=CONFIG_FILE,
            help='config file (default: '+CONFIG_FILE+')')
    parser.add_argument('-s', '--sheet', nargs='+', type=str, action='extend',
            help='use listed Google sheets')
    parser.add_argument('-a', '--add', action="store_true",
            help='enable to add missing items into the Google spreadsheet')
    parser.add_argument('-r', '--remove', action="store_true",
            help='enable removing items in the Google spreadsheet')
    parser.add_argument('-f', '--file', type=str, default=None,
            help='file name of data source')
    parser.add_argument('-t', '--table', type=str, default=None,
            help='table name of the spreadsheet source')
    parser.add_argument('-o', '--offset', type=int, default=None,
            help='header offset in the spreadsheet source')
    parser.add_argument('-v', '--verbose', action='count', dest='verbosity',
            default=0, help='verbose output (repeat for increased verbosity)')
    parser.add_argument('-q', '--quiet', action='store_const', const=-1,
            default=0, dest='verbosity', help='quiet output (show errors only)')
    parser.add_argument('-n', '--noupdate', action="store_true",
            help='disable Google spreadsheet update')
    args = parser.parse_args()
    log.setup(args.verbosity)
    return args

def get_sheets(config, selected_sheets):
    """ Get valid sheets list """
    sheets_list = []
    if not selected_sheets:
        sheets_list = config.sheets
    else:
        for item in selected_sheets:
            if not item in config.sheets:
                log.error(UNKNOWN_SHEET + item)
            else:
                sheets_list.append(item)
    return sheets_list

def get_sheets_and_data(source_access, config, selected_sheets, google_spreadsheet):
    """ Get valid sheets list and source data """
    source_data = {}
    sheets_list = []
    for sheet_name, query in config.queries.items():
        if sheet_name in selected_sheets:
            if config.sheet[sheet_name].default_columns:
                source_data[sheet_name] = SourceData(source_access.get_data(sheet_name, query), \
                    config.sheet[sheet_name], google_spreadsheet.data[sheet_name])
            else:
                source_data[sheet_name] = SourceData(source_access.get_data(sheet_name, query), \
                    config.sheet[sheet_name])
            sheets_list.append(sheet_name)
    log.check_error()
    return sheets_list, source_data

def normalize_type(value):
    """ Avoid numpy type int64 issue that is not allowed in JSON """
    if numpy.issubdtype(type(value), int):
        value = int(value)
    return value

def update_google_row_data(s_sheet, s_key_index, g_sheet, g_row, formula=None):
    """ Update the Google row with source data """
    for column in g_sheet.columns:
        if column in s_sheet.data.columns:
            value = normalize_type(s_sheet.data.loc[s_key_index, (column)])
            if value == '' and formula and column in formula:
                value = formula[column]
            g_sheet.loc[g_row, (column)] = value
        else:
            if formula and column in formula:
                value = formula[column]
            else:
                value = ""
            try:
                if pd.isnull(g_sheet.loc[g_row, (column)]):
                    g_sheet.loc[g_row, (column)] = normalize_type(value)   # fix undefined value
            # Fix undefined variable or value issue
            except (KeyError, ValueError):
                g_sheet.loc[g_row, (column)] = normalize_type(value)

def get_formula(source, google, sheet_name, sheet_conf):
    """
    Get formula in Google columns, that are not included in the source columns,
    from the last row.
    """
    formula = {}
    if sheet_conf[sheet_name].inherit_formulas:
        for column in google.data[sheet_name].columns:
            if column not in list(sheet_conf[sheet_name].columns.keys()) or \
                    sheet_conf[sheet_name].default_columns and \
                    column not in source[sheet_name].data.columns:
                try:
                    cell = google.data[sheet_name].at[len(google.data[sheet_name])-1, column]
                except KeyError:
                    continue
                try:
                    if cell[0] == "=":
                        formula[column] = cell
                except (IndexError, TypeError):
                    continue
    return formula

def transform_data(source, google, sheet_conf, args):
    """ Copy transformed data from source to the target Google spreadsheet """
    missing_all_google_key_values = []
    for sheet_name in google.active_sheets:
        key = sheet_conf[sheet_name].key
        # Update Google sheet data
        for row in google.data[sheet_name].index:
            try:
                key_value = str(google.data[sheet_name][key][row])
            except KeyError as exception:
                log.error(exception)
                log.fatal_error(UNKNOWN_KEY + sheet_name)
            if key_value in source[sheet_name].key_dict:
                key_index = source[sheet_name].key_dict[key_value]
                source[sheet_name].used_key[key_value] = True
            else:
                if key_value:
                    message = key + ': ' + key_value + NOT_AVAILABLE + sheet_name
                else:
                    message = key + ': <empty key>' + NOT_AVAILABLE + sheet_name
                if args.remove:
                    log.info(message)
                else:
                    log.warning(message)
                google.remove_rows[sheet_name].append(row)
                continue
            update_google_row_data(source[sheet_name], key_index, google.data[sheet_name], row)
        # Identify missing keys in the Google sheet which data are available from the source
        missing_google_keys = source[sheet_name].check_missing_keys(sheet_name, key, \
                sheet_conf[sheet_name], args.add)
        if args.add and not args.noupdate:
            formula = get_formula(source, google, sheet_name, sheet_conf)
            for key_value in missing_google_keys:
                update_google_row_data(source[sheet_name], source[sheet_name].key_dict[key_value], \
                        google.data[sheet_name], len(google.data[sheet_name]), formula)
        missing_all_google_key_values = missing_all_google_key_values + missing_google_keys

    if missing_all_google_key_values:
        pyperclip.copy('\n'.join(map(str, missing_all_google_key_values)))

def update_google_data(google, sheets_list, sheet_conf, enable_remove):
    """ Update Google spreadsheet """
    google.update_spreadsheet()
    for sheet_name in sheets_list:
        for column in sheet_conf[sheet_name].columns:
            if sheet_conf[sheet_name].columns[column].link and \
                    sheet_conf[sheet_name].key == column:
                google.update_column_with_links(sheet_name, column, \
                        sheet_conf[sheet_name].columns[column].link)
        if enable_remove and google.remove_rows[sheet_name]:
            removals = {}
            start_row = None
            previous_row = None
            for current_row in sorted(google.remove_rows[sheet_name]):
                if start_row is None or current_row != previous_row + 1:
                    start_row = current_row
                    previous_row = current_row
                    removals[start_row] = 1
                else:
                    previous_row = current_row
                    removals[start_row] = removals[start_row] + 1
            for row in sorted(removals, reverse=True):
                google.delete_rows(sheet_name, row+sheet_conf[sheet_name].header_offset+1, \
                        removals[row])

def main():
    """
    Get the config file, read source data and write them
    into the google spreadsheet.
    """
    log.debug(SCRIPT_STARTED)
    args = get_cli_parameters()
    if args.noupdate:
        log.info(NO_UPDATE_MODE)
    config = Config(args.config)
    if config.source == 'BUGZILLA':
        source_access = Bzilla(config.bugzilla_domain, config.bugzilla_url, config.bugzilla_api_key)
    elif config.source == 'JIRA':
        source_access = Jira(config.jira_server, config.jira_token, config.jira_max_results)
    elif config.source == 'FILE':
        source_access = Xsheet(config, args.file, args.table, args.offset)
    else:
        log.error(UNKNOWN_SOURCE)
    log.check_error()    # if a source error occured, terminate the script
    valid_sheets = get_sheets(config, args.sheet)
    google_spreadsheet = Gsheet(config.spreadsheet_id, valid_sheets, config.sheet)
    used_sheets_list, data = get_sheets_and_data(source_access, config, \
            valid_sheets, google_spreadsheet)
    transform_data(data, google_spreadsheet, config.sheet, args)
    if not args.noupdate:
        update_google_data(google_spreadsheet, used_sheets_list, config.sheet, args.remove)
    log.debug(SCRIPT_FINISHED)
