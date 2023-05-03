import pathlib
import time
import subprocess
import threading
from typing import Callable
import discord
from discord.member import VoiceState
from discord.voice_client import VoiceClient
from discord.opus import _OpusStruct
import asyncio
import os
import yt_dlp
from enum import Enum
from dataclasses import dataclass
import ffmpeg
import logging


token  = open('token.txt', 'r').read()
CHANNEL_LOGGER_FILE = "channel_logger.txt"
COMMANDS_FILE = "commands.txt" #aka the !help list of what commands do

class CustomConsoleFormatter(logging.Formatter):

    grey = "\x1b[38;21m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    green = "\x1b[32;21m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: green + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

class DiscordLogger:
    def __init__(self, channel, loop,  level: int = logging.INFO) -> None:
        self.channel:discord.abc.Messageable = channel
        self.level = level
        self.loop = loop
    def handle(self, record: logging.LogRecord):
        self.loop.create_task(self.channel.send(f'**{record.levelname}**: {record.getMessage()}'))
    #async def flush(self):
    #    pass
    #async def write(self, msg):
    #    await self.channel.send("I am send from discord" + msg)

@dataclass
class Music:
    youtube_url: str = ""
    stream: str = "" # Can either be file location or a youtube stream (other streams are possible as well)
    id: str = ""
    title: str = ""

class GuildInstance:
    def __init__(self, guild_id) -> None:
        self.guild_id: int = guild_id 
        self.voice_client: VoiceClient = None
        self.playlist:asyncio.Queue = asyncio.Queue()
        self.music_playing: Music = None
        self.repeat: bool = False
        self.logger: logging.Logger = logging.Logger(f'{guild_id}')

class TnTAudioSource(discord.voice_client.AudioSource):
    def __init__(self, stream, log:Callable):
        self.log = log
        in_args= {
            "reconnect": "1",
            "reconnect_streamed": "1",
            "reconnect_delay_max": "5"
        }
        out_args = {
            "format": "s16le",
            "ar": "48000",
            "ac": "2",
            "loglevel": "warning"
        }
        self.process: subprocess.Popen = (
            ffmpeg.input(stream, **in_args)
            .output('pipe:', **out_args)
            .run_async(pipe_stdout=True, pipe_stderr=True)
        )
        self.running = True
        self.get_error_task= threading.Thread(target=self.get_error)
        self.get_error_task.start()
        
    def read(self):
        ret = self.process.stdout.read(_OpusStruct.FRAME_SIZE)
        if len(ret) != _OpusStruct.FRAME_SIZE:
            return b''
        return ret

    def get_error(self):
        while self.running == True:
            read_msg = self.process.stderr.readline().decode("utf-8")
            if len(read_msg) > 1:
                self.log(logging.WARNING, read_msg)
            time.sleep(0.1)

    def cleanup(self):
        
        try:
            self.process.kill()
        except Exception:
            self.log(logging.DEBUG, f"Ignoring error attempting to kill ffmpeg process {self.process.pid}")
        
        
        if self.process.poll() is None:
            self.log(logging.DEBUG, f'ffmpeg process {self.process.pid} has not terminated. Waiting to terminate...')
            self.process.communicate()
            self.log(logging.DEBUG, f'ffmpeg process {self.process.pid} should have terminated with a return code of {self.process.returncode}.')
        else:
            self.log(logging.DEBUG, f'ffmpeg process {self.process.pid} successfully terminated with return code of {self.process.returncode}.')

    def __del__(self):
        self.running = False
        self.get_error_task.join()
        self.cleanup()
        return super().__del__()


#To ensure we only trigger or bot on message that include this
class Commands(Enum):
    UNKNOWN = 0
    HELP = 1
    PLAY = 2
    RESUME = 3
    PAUSE = 4
    SKIP = 5
    QUEUE = 6
    LOOP = 7
    CLEAR_QUEUE = 8
    QUIT = 9
    LOG = 100
    def from_string(string:str) -> Enum:
        if string == '!help':
            return Commands.HELP
        elif string == '!play':
            return Commands.PLAY
        elif string == '!resume' or string == "!continue":
            return Commands.RESUME
        elif string == '!pause':
            return Commands.PAUSE
        elif string == '!skip':
            return Commands.SKIP
        elif string == '!queue' or string == "!playlist":
            return Commands.QUEUE
        elif string == '!loop' or string == "!repeat":
            return Commands.LOOP
        elif string == '!clear':
            return Commands.CLEAR_QUEUE
        elif string == '!quit' or string == "!leave":
            return Commands.QUIT
        elif string == '!log':
            return Commands.LOG
        else:
            return Commands.UNKNOWN

class TnTRhythmBot(discord.Client):
    def __init__(self, *, loop=None, **options):
        super().__init__(loop=loop, **options)
        #Map to ensure that the right music plays in the right guild/server
        self.guildMap = {}
        self.logger = logging.Logger("TnTRhythm")
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)

        ch.setFormatter(CustomConsoleFormatter())
        self.logger.addHandler(ch)
        if pathlib.Path("TnTRhythm.log").exists():
            os.remove("TnTRhythm.log")

        fh = logging.FileHandler("TnTRhythm.log")
        fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"))
        fh.setLevel(logging.DEBUG)
        self.logger.addHandler(fh)

        self.channel_loggers = {}

    async def on_ready(self):
        self.add_loggers()
        self.log(None, logging.DEBUG, f'{self.user} has connected to Discord!')
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="!help"))
    
    async def add_to_playlist(self, guild_instance: GuildInstance,  songs:list):
        """Add a list of song/music YouTube link to the playlist

        :param guild_instance: [description]
        :type guild_instance: GuildInstance
        :param songs: The list of song/music links
        :type songs: list
        """
        self.log(guild_instance, logging.DEBUG, f"added to playlist: {songs}")
        for music in await self.get_music(guild_instance, songs):
            await guild_instance.playlist.put(music)

    async def on_message(self, message: discord.message.Message):
        if message.author == self.user:
            return
        #Get the guild instanced that sent the message
        args:list = message.content.split(" ")

        if message.guild.id not in self.guildMap:
            self.guildMap[message.guild.id] = GuildInstance(message.guild.id)

        guild_instance: GuildInstance = self.guildMap[message.guild.id]
        if len(args) <= 0 or len(args[0]) <= 0 or args[0][0] != "!":
            return
        command = Commands.from_string(args[0])
        if command == Commands.UNKNOWN:
            return #Not a command we trigger on

        elif command == Commands.PLAY and len(args) >= 2:
            try:
                await self.play_command(guild_instance, message.author.voice, args[1:])
            except Exception as e:
                self.log(guild_instance, logging.ERROR, f'failed to play music with exception: {e}')

        elif command == Commands.LOG:
            try:
                self.add_new_logger(guild_instance, message.channel, args[1:])
            except Exception as e:
                self.log(guild_instance, logging.ERROR, f'failed to add a new logger with exception: {e}')

        elif command == Commands.HELP:
            command_help = open(COMMANDS_FILE, "r").read()
            msg =f"```\n{command_help}\n```"
            await self.send_message(msg, message.channel)

        #Ensure we have a voice client and is connected
        elif guild_instance.voice_client == None or not guild_instance.voice_client.is_connected():
            self.log(guild_instance, logging.INFO, "Most be connected to a voice chat if running any commands except !play, !log")
            return
        #COMMADS BELOW HERE REQUIRES A VOICE CLIENT AND A CONNETION TO A VOICE CHANNEL  
        elif command == Commands.PLAY or command == Commands.RESUME:
            if guild_instance.voice_client.is_paused():
                self.log(guild_instance, logging.DEBUG, "The Resume/Play Command has been given")
                guild_instance.voice_client.resume()
            else:
                self.log(guild_instance, logging.INFO, "Nothing to play/resume")
                
        elif command == Commands.PAUSE:
            if guild_instance.voice_client.is_playing():
                self.log(guild_instance, logging.DEBUG, "The Pause Command has been given")
                guild_instance.voice_client.pause()

        elif command == Commands.QUIT:
            self.log(guild_instance, logging.DEBUG, "Good bye, I leave now")
            try:
                self.clear_playlist(guild_instance)
            except Exception as e:
                self.log(guild_instance, logging.ERROR, f'failed to clear playlist while quiting with exception: {e}')
            guild_instance.repeat = False
            guild_instance.voice_client.stop()
            await guild_instance.voice_client.disconnect()

        elif command == Commands.SKIP:
            if guild_instance.voice_client.is_playing():
                self.log(guild_instance, logging.DEBUG, "Trying to skip this banger")
                guild_instance.repeat = False
                guild_instance.voice_client.stop()

        elif command == Commands.QUEUE:
            msg_playlist = self.get_printable_playlist(guild_instance)
            await self.send_message(msg_playlist,  message.channel)

        elif command == Commands.LOOP:
            if guild_instance.voice_client.is_playing():
                guild_instance.repeat = not guild_instance.repeat
                self.log(guild_instance, logging.INFO, f'Repeat set to {guild_instance.repeat}')

        elif command == Commands.CLEAR_QUEUE:
            try:
                self.clear_playlist(guild_instance)
            except Exception as e:
                self.log(guild_instance, logging.ERROR, f'failed to clear playlist with exception: {e}')

    async def play_command(self, guild_instance: GuildInstance, voice_state:VoiceState, songs:list):
        if(voice_state == None):
            self.log(guild_instance, logging.INFO, "Unable to find voice chat to join (you must be in a voice chat channel when calling the !play command")
            return

        v_c: discord.VoiceChannel = voice_state.channel
        if v_c == None:
            self.log(guild_instance, logging.INFO, "Okay I don't know exactly why I can't find the channel, tell me what you did to get this")
            return
        await self.add_to_playlist(guild_instance, songs)
        if(guild_instance.voice_client != None and guild_instance.voice_client.is_connected()):
            if guild_instance.voice_client.is_playing():
                return
            self.log(guild_instance, logging.DEBUG, "Trying to play music from a VC I am in")
            await self.play_sound(guild_instance)
        else:
            guild_instance.voice_client = await v_c.connect()
            self.log(guild_instance, logging.DEBUG, "Trying to play music from a VC I just connected to")
            await self.play_sound(guild_instance)

    def add_loggers(self):
        if not pathlib.Path(CHANNEL_LOGGER_FILE).exists():
            return

        #Add the channel loggers
        for channel_logger in open(CHANNEL_LOGGER_FILE, "r").readlines():
            guild_id_str, channel_str_id, channel_level_str = channel_logger.split()
            guild_id = int(guild_id_str)
            if guild_id not in self.guildMap:
                self.guildMap[guild_id] = GuildInstance(guild_id)

            channel_id = int(channel_str_id)
            channel_level = int(channel_level_str)

            channel = self.get_channel(id = channel_id)
            if channel == None:
                self.log(self.guildMap[guild_id], logging.WARNING, f"Could not find the channel: {channel_id}")
                continue


            if guild_id in self.channel_loggers:
                if channel_id in self.channel_loggers[guild_id]:
                    return #Already exist (this mostly happen when on_ready get called again due to losing connect)
            else:
                self.channel_loggers[guild_id] = dict()

            self.channel_loggers[guild_id][channel_id] = DiscordLogger(channel, self.loop, channel_level)
            self.guildMap[guild_id].logger.addHandler(self.channel_loggers[guild_id][channel_id])
            
            self.log(self.guildMap[guild_id], logging.DEBUG, f"Added a {logging.getLevelName(channel_level)} from logger file g_id: {guild_id} ch_id: {channel_id}")

    def remove_logger(self, guild_instance: GuildInstance, channel_id):
        if guild_instance.guild_id in self.channel_loggers:
            if channel_id in self.channel_loggers[guild_instance.guild_id]:
                self.log(guild_instance, logging.INFO, "Removing logger!")           
                guild_instance.logger.removeHandler(self.channel_loggers[guild_instance.guild_id][channel_id])
                del self.channel_loggers[guild_instance.guild_id][channel_id]

                # remove it from the logger file
                with open(CHANNEL_LOGGER_FILE, "w") as f:
                    for guild_id, val in self.channel_loggers.items():
                        for channel_id, channel in val.items():
                            f.write(f'{guild_id} {channel_id} {channel.level}\n')
            else:
                self.send_message("There is no logger in the channel to remove", self.get_channel(id = channel_id))
        else:
            self.send_message("There is no logger in this guild to remove", self.get_channel(id = channel_id))

    def add_new_logger(self, guild_instance: GuildInstance, channel, logger_arg):
        guild_id = guild_instance.guild_id
        new_logger_level = logging.INFO
        if len(logger_arg) >= 1:
            log_level_txt: str = logger_arg[0].upper()

            if log_level_txt in logging._nameToLevel:
                new_logger_level = logging._nameToLevel[log_level_txt]
            elif log_level_txt == "REMOVE":
                pass
            else:
                #Return a message about falling to create a logger to sender
                self.send_message(f'{log_level_txt} is not a valid logging level (CRITICAL, ERROR, WARNING, INFO, DEBUG or REMOVE)', channel)
                return
        channel_id = channel.id
        if len(logger_arg) == 2:
            #TODO: a try except incase the convertion fails
            channel_id = int(logger_arg[1])
        if log_level_txt == "REMOVE":
            self.remove_logger(guild_instance, channel_id)
            return

        if guild_id in self.channel_loggers:
            if channel_id in self.channel_loggers[guild_id]:
                if self.channel_loggers[guild_id][channel_id].level != new_logger_level:
                    self.log(guild_instance, logging.DEBUG, "There already exist a logger, but changling level")
                    self.channel_loggers[guild_id][channel_id].level = new_logger_level
                else:
                    self.log(guild_instance, logging.INFO, "There already exist a logger with this level here")
                return #
        else:
            self.log(guild_instance, logging.DEBUG, "New channel who this")
            self.channel_loggers[guild_id] = dict()
        # Save the changes in
        self.channel_loggers[guild_id][channel_id] = DiscordLogger(channel, self.loop, new_logger_level)
        guild_instance.logger.addHandler(self.channel_loggers[guild_id][channel_id])
        with open(CHANNEL_LOGGER_FILE, "w") as f:
            for guild_id, val in self.channel_loggers.items():
                for channel_id, channel in val.items():
                    f.write(f'{guild_id} {channel_id} {channel.level}\n')
        self.log(guild_instance, logging.INFO, f"Created a {log_level_txt} Logger")

    async def clear_playlist(self, guild_instance: GuildInstance):
        while not guild_instance.playlist.empty():
            await guild_instance.playlist.get()
            guild_instance.playlist.task_done()
    
    def get_printable_playlist(self, guild_instance: GuildInstance) -> str:
        """Create a printable playlist of current music and music in queue

        :param guild_instance: The guild instance in which the playlist exist
        :type guild_instance: GuildInstance
        :return: Printable message of playlist
        :rtype: str
        """
        i: int = 1
        msg: str = "```\n"
        if guild_instance.music_playing != None:
            msg += f'Currently Playing: {guild_instance.music_playing.title}'
            if guild_instance.repeat:
                msg += ' (on repeat)'
            msg += '\n'
        #Kinda bad to call that private variable, but I need a quick read-only of the queue. Consider another structure
        for music in guild_instance.playlist._queue:
            msg += f'{i}. {music.title}\n'
            i += 1
        msg += "```"
        return msg
        #await self.send_message(msg, channel)
    
    async def play_sound(self, guild_instance: GuildInstance):
            def music_log(level, msg):
                self.log(guild_instance, level, msg)
            while not guild_instance.playlist.empty():
                music_to_play:Music = await guild_instance.playlist.get()
                while True: #It's a do while guild_instance.repeat == True
                    def after_log(e):
                        if e is None:
                            self.log(guild_instance, logging.DEBUG, f"Done playing '{music_to_play.title}'")
                        else:
                            self.log(guild_instance, logging.ERROR, f"Done playing '{music_to_play.title}, got error: {e}")

                    guild_instance.voice_client.play(TnTAudioSource(music_to_play.stream, music_log), after=after_log )
                    #guild_instance.voice_client.source = discord.PCMVolumeTransformer(guild_instance.voice_client.source)
                    guild_instance.music_playing = music_to_play
                    self.log(guild_instance, logging.DEBUG, "The play command (in the code) has been given, and we are _trying_ jam")
                    while guild_instance.voice_client.is_playing():
                        await asyncio.sleep(0.5)
                    if guild_instance.repeat == False:
                        break
                guild_instance.playlist.task_done()
            self.log(guild_instance, logging.DEBUG, "I have played songs, and now my playlist is empty, so are we just gonna sit here in silence?")
            guild_instance.music_playing = None
    
    async def get_music(self, guild_instance: GuildInstance, urls:list):
        ret = list()
        for url in urls:
            ydl_opts = {
                'format': 'bestaudio/best',
                'logger': guild_instance.logger
            }
            
            video_info = yt_dlp.YoutubeDL(ydl_opts).extract_info(url= url, download=False)
            ret.append(Music(url,  video_info['url'], video_info['id'], video_info['title']))
        return ret

    async def send_message(self, msg: str, channel:discord.abc.Messageable):
        await channel.send(msg)

    def log(self, guild_instance: GuildInstance, level: int, msg: str):
        self.logger.log(level, msg)
        if guild_instance is None:
            #Log to every logger
            for id, gi in self.guildMap.items():
                if gi.logger is not None:
                    gi.logger.log(level, msg)
        else:
            if guild_instance.logger is not None:
                guild_instance.logger.log(level, msg)
        
intents = discord.Intents.default()
intents.message_content = True
client = TnTRhythmBot(intents=intents)
client.run(token)