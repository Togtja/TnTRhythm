import pathlib
import discord
from discord.voice_client import VoiceClient
import asyncio
import os
import yt_dlp

import logging


token  = open('token.txt', 'r').read()
CHANNEL_LOGGER_FILE = "channel_logger.txt"
COMMANDS_FILE = "commands.txt" #aka the !help list of what commands do

class CustomFormatter(logging.Formatter):

    grey = "\x1b[38;21m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
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

class Music:
    youtube_url: str = ""
    stream: str = "" # Can either be file location or a youtube stream (other streams are possible as well)
    id: str = ""
    title: str = ""
    downloaded: bool = False

class GuildInstance:
    def __init__(self, guild_id) -> None:
        self.guild_id: int = guild_id 
        self.voice_client: VoiceClient = None
        self.playlist:asyncio.Queue = asyncio.Queue()
        self.music_playing: Music = None
        self.repeat: bool = False
        self.logger: logging.Logger = logging.Logger(f'{guild_id}')


class TnTRhythmBot(discord.Client):
    def __init__(self, *, loop=None, **options):
        super().__init__(loop=loop, **options)
        #Map to ensure that the right music plays in the right guild/server
        self.guildMap = {}
        self.logger = logging.Logger("TnTRhythm")
        self.logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)

        ch.setFormatter(CustomFormatter())
        self.logger.addHandler(ch)
        self.channel_loggers = {}

    async def on_ready(self):
        self.add_loggers()
        self.log(None, logging.DEBUG, f'{self.user} has connected to Discord!')

    
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
        #print(type(message.channel))
        if message.author == self.user:
            return
        #Get the guild instanced that sent the message
        args:list = message.content.split(" ")

        if message.guild.id not in self.guildMap:
            self.guildMap[message.guild.id] = GuildInstance(message.guild.id)

        guild_instance: GuildInstance = self.guildMap[message.guild.id]
        if len(args) <= 0:
            return
        elif args[0][0] != "!":
            return
        if args[0] == "!play" and len(args) >= 2:
            if(message.author.voice == None):
                self.log(guild_instance, logging.INFO, "Unable to find voice chat to join (you must be in a voice chat channel when calling the !play command")
                return

            v_c: discord.VoiceChannel = message.author.voice.channel
            if v_c == None:
                self.log(guild_instance, logging.INFO, "Okay I don't know exactly why I can't find the channel, tell me what you did to get this")
                return
            await self.add_to_playlist(guild_instance, args[1:])
            if(guild_instance.voice_client != None and guild_instance.voice_client.is_connected()):
                if guild_instance.voice_client.is_playing():
                    return
                self.log(guild_instance, logging.DEBUG, "Trying to play music from a VC I am in")
                await self.play_sound(guild_instance)
            else:
                guild_instance.voice_client = await v_c.connect()
                self.log(guild_instance, logging.DEBUG, "Trying to play music from a VC I just connected to")
                await self.play_sound(guild_instance)
        elif args[0] == "!log":
            self.add_new_logger(guild_instance, message.channel, args[1:])
        elif args[0] == "!help":
            command_help = open(COMMANDS_FILE, "r").read()
            msg =f"```\n{command_help}\n```"
            await self.send_message(msg, message.channel)
        elif guild_instance.voice_client == None or not guild_instance.voice_client.is_connected():
            self.log(guild_instance, logging.INFO, "Most be connected to a voice chat if running any commands except !play, !log")
            return
        #COMMADS BELOW HERE REQUIRES A VOICE CLIENT AND A CONNECT TO A VOICE CHANNEL  
        elif args[0] == "!play" or args[0] == "!resume" or args[0] == "!continue":
            if guild_instance.voice_client.is_paused():
                self.log(guild_instance, logging.DEBUG, "The Resume/Play Command has been given")
                guild_instance.voice_client.resume()
            else:
                self.log(guild_instance, logging.INFO, "Nothing to play/resume")
        elif args[0] == "!pause":
            if guild_instance.voice_client.is_playing():
                self.log(guild_instance, logging.DEBUG, "The Pause Command has been given")
                guild_instance.voice_client.pause()        
        elif args[0] == "!quit" or args[0] == "!leave":
            self.log(guild_instance, logging.DEBUG, "Good bye, I leave now")
            self.clear_playlist(guild_instance)
            guild_instance.repeat = False
            guild_instance.voice_client.stop()
            await guild_instance.voice_client.disconnect()
        elif args[0] == "!skip":
            if guild_instance.voice_client.is_playing():
                self.log(guild_instance, logging.DEBUG, "Trying to skip this banger")
                guild_instance.repeat = False
                guild_instance.voice_client.stop()
        elif args[0] == "!queue" or args[0] == "!playlist":
            msg_playlist = self.get_printable_playlist(guild_instance)
            await self.send_message(msg_playlist,  message.channel)
        elif args[0] == "!repeat" or args[0] == "!loop":
            if guild_instance.voice_client.is_playing():
                guild_instance.repeat = not guild_instance.repeat
                self.log(guild_instance, logging.INFO, f'Repeat set to {guild_instance.repeat}')
        elif args[0] == "!clear":
            self.clear_playlist(guild_instance)

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
                    return #Nothing changed
            else:
                self.log(guild_instance, logging.DEBUG, "New channel who this")
                self.channel_loggers[guild_id][channel_id] = dict()
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
            while not guild_instance.playlist.empty():
                music_to_play:Music = await guild_instance.playlist.get()
                while not music_to_play.downloaded:
                     await asyncio.sleep(0.5)
                while True: #It's a do while guild_instance.repeat == True
                    FFMPEG_OPTS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
                    def after_log(e):
                        if e is None:
                            self.log(guild_instance, logging.DEBUG, f"Done playing '{music_to_play.title}'")
                        else:
                            self.log(guild_instance, logging.ERROR, f"Done playing '{music_to_play.title}, got error: {e}")
                    #self.loop.create_task(after_log)
                    guild_instance.voice_client.play(discord.FFmpegPCMAudio(music_to_play.stream, **FFMPEG_OPTS), after=after_log )
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
        for u in urls:
            m = Music()
            m.youtube_url = u

            ydl_opts = {
                'format': 'bestaudio/best',
                'logger': guild_instance.logger
            }
            
            video_info = yt_dlp.YoutubeDL(ydl_opts).extract_info(url= m.youtube_url, download=False)
            m.id = video_info['id']
            m.title = video_info['title']
            m.stream = video_info['formats'][0]['url']
            m.downloaded = True
            ret.append(m)
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
        

client = TnTRhythmBot()
client.run(token)