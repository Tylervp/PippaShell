from aiosmb.commons.connection.url import SMBConnectionURL
from aiosmb.commons.interfaces.machine import SMBMachine
from aiosmb.commons.interfaces.share import SMBShare
from aiosmb.external.aiocmd.aiocmd import aiocmd
from aiosmb import logger
from aiosmb.commons.interfaces.file import SMBFile
from aiosmb.commons.exceptions import SMBException, SMBMachineException
from aiosmb.dcerpc.v5.rpcrt import DCERPCException

import logging as log
import traceback
import ntpath

from copy import deepcopy


class SMBClient(aiocmd.PromptToolkitCmd):
    def __init__(self, url=None):
        aiocmd.PromptToolkitCmd.__init__(self, ignore_sigint=False)  # Setting this to false, since True doesnt work on windows...
        self.conn_url = None
        if url:
            self.conn_url = SMBConnectionURL(url)
        self.connection = None
        self.machine = None
        self.shares = {}  # name -> share
        self.__current_share = None
        self.__current_directory = None

    async def do_login(self, url=None):
        """Connects to the remote machine"""
        try:
            # cred = self.conn_url.get_credential()
            self.connection = self.conn_url.get_connection()

            # Make sure each connection has its own list of supported dialects
            # before logging in. By default, the supported dialects are a
            # reference to the same object. But inside SMBConnection, this
            # list is mutated, causing problems when the list is shared
            # across multiple threads. This is a bug in the library.
            # The offending line in the source:
            #    https://github.com/skelsec/aiosmb/blob/435fcd2/aiosmb/connection.py#L154

            self.connection.supported_dialects = deepcopy(self.connection.supported_dialects)
            _, err = await self.connection.login()
            if err:
                raise err
            self.machine = SMBMachine(self.connection)
            return True, None
        except Exception as e:
            return False, e

    async def do_logout(self):
        if self.machine:
            await self.machine.close()
        self.machine = None

        if self.connection:
            try:
                await self.connection.terminate()
            except:
                log.exception('connection.close')
        self.connection = None

    async def _on_close(self):
        await self.do_logout()

    async def do_shares(self, show=False):
        """Lists available shares"""
        try:
            shareslist = []
            if self.machine is None:
                return False, Exception('Not logged in!')
            async for share, err in self.machine.list_shares():
                if err:
                    raise err
                self.shares[share.name] = share
                shareslist.append(share)
            return shareslist

        except Exception as e:
            log.debug(traceback.format_exc())
            return None, e

    async def do_use(self, share_name):
        """selects share to be used"""
        try:
            self.__current_share = SMBShare.from_unc(share_name)
            _, err = await self.__current_share.connect(self.connection)
            if err:
                return None, err
            self.__current_directory = self.__current_share.subdirs['']  # this is the entry directory
            self.prompt = '[%s]$ ' % self.__current_directory.unc_path
            _, err = await self.do_refreshcurdir()
            if err:
                return None, err
            return True, None

        except Exception as e:
            log.debug(traceback.format_exc())
            return None, e

    async def do_refreshcurdir(self):
        try:
            async for entry in self.machine.list_directory(self.__current_directory):
                # no need to put here anything, the dir bject will store the refreshed data
                pass
            return True, None
        except Exception as e:
            log.debug(traceback.format_exc())
            return None, e

    async def do_getdirsd(self):
        sd, err = await self.__current_directory.get_security_descriptor(self.connection)
        if err:
            raise err
        return sd

    async def do_get(self, folder, file, localfile):
        """Download a file from the remote share to the current folder"""
        try:
            with open('%s/%s' % (folder, localfile), 'wb') as outfile:
                async for data, err in self.machine.get_file_data(file):
                    if err is not None:
                        raise err
                    if data is None:
                        break
                    outfile.write(data)
            return True, None
        except Exception as e:
            return None, e

    async def do_enumall(self, depth):
        """ Enumerates all shares for all files and folders recursively """
        async for path, otype, err in self.__current_directory.list_r(self.connection, depth=int(depth)):
            if otype == 'file':
                yield path

    async def do_ls(self):
        return await self.__current_directory.list(self.connection)

    async def get_subdirs(self):
        return self.__current_directory.subdirs

    async def do_session_enum(self):
        try:
            async for session, err in self.machine.list_sessions():
                if err:
                    raise err
                yield session
        except:
            pass

    async def do_priv_session_enum(self):
        try:
            async for session, err in self.machine.priv_list_sessions():
                if err:
                    raise err
                yield session
        except AttributeError:
            log.debug(traceback.format_exc())
            log.critical('It seems as though you do not have the proper version of aiosmb installed. Please install the proper version. You can find more information in the readme.')
        except:
            log.debug(traceback.format_exc())

    async def do_cd(self, directory_name):
        try:
            if directory_name not in self.__current_directory.subdirs:
                if directory_name == '..':
                    self.__current_directory = self.__current_directory.parent_dir
                    return False
                else:
                    return True
            else:
                self.__current_directory = self.__current_directory.subdirs[directory_name]
                self.prompt = '[%s] $' % (self.__current_directory.unc_path)
                _, err = await self.do_refreshcurdir()
                if err is not None:
                    raise err

                return False
        except Exception as e:
            log.debug(traceback.print_exc())
            return True

    async def do_rdp_enumeration(self):
        try:
            async for session, err in self.machine.rdp_enumeration():
                if err:
                    raise err
                yield session
        except AttributeError:
            log.debug(traceback.format_exc())
            log.critical('It seems as though you do not have the proper version of aiosmb installed. Please install the proper version. You can find more information in the readme.')
        except:
            log.debug(traceback.format_exc())


    async def do_put(self, file_name):
        """Uploads a file to the remote share"""
        try:
            if self.__current_share.name is None:
                self.__current_share.name = self.__current_share.unc_path.split('\\')[-1]
            basename = ntpath.basename(file_name)
            dst = '\\%s\\%s\\%s' % (self.__current_share.name, self.__current_directory.fullpath, basename)
            _, err = await self.machine.put_file(file_name, dst)
            if err is not None:
                print('Failed to put file! Reason: %s' % err)
                return False, err
            _, err = await self.do_refreshcurdir()
            if err is not None:
                raise err
            return True, None

        except SMBException as e:
            logger.debug(traceback.format_exc())
            print(e.pprint())
            return None, e
        except SMBMachineException as e:
            logger.debug(traceback.format_exc())
            print(str(e))
            return None, e
        except DCERPCException as e:
            logger.debug(traceback.format_exc())
            print(str(e))
            return None, e
        except Exception as e:
            traceback.print_exc()
            return None, e


    async def enumerate_services(self):
        try:
            async for service, err in self.machine.list_services():
                if err:
                    raise err
                yield service
        except:
            log.debug(traceback.format_exc())
