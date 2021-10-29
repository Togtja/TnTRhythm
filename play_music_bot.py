import discord
from discord.voice_client import VoiceClient
import asyncio
import os
import yt_dlp

class Music:
    youtube_url: str = ""
    file_name: str = ""
    id: str = ""
    title:str = ""
    downloaded: bool = False

class GuildInstance:
    voice_client: VoiceClient = None
    playlist:asyncio.Queue = asyncio.Queue()
    music_playing: Music = None
    repeat = False

token  = open('token.txt', 'r').read()
class TnTRhythmBot(discord.Client):
    def __init__(self, *, loop=None, **options):
        super().__init__(loop=loop, **options)
        self.guildMap = {}
    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
    
    async def add_to_queue(self, guild_instance: GuildInstance,  songs):
        print("added to queue", songs)
        for music in await self.get_music(songs):
            await guild_instance.playlist.put(item=music)

    async def on_message(self, message: discord.message.Message):
        #print(type(message.author))
        if message.author == self.user:
            return

        args = message.content.split(" ")
        if message.guild not in self.guildMap:
            self.guildMap[message.guild] = GuildInstance()

        guild_instance = self.guildMap[message.guild]
        if len(args) <= 0:
            return
        if args[0] == "!play" and len(args) >= 2:
            if(message.author.voice == None):
                print("Where is the voice channel? hmmm?")
                return
            v_c = message.author.voice.channel
            if v_c == None:
                print("Sadness, no channel")
                return
            await self.add_to_queue(guild_instance, args[1:])
            if(guild_instance.voice_client != None and guild_instance.voice_client.is_connected()):
                if guild_instance.voice_client.is_playing():
                    return
                print("playing from existing")
                await self.play_sound(guild_instance)
            else:
                guild_instance.voice_client = await v_c.connect()
                print("Play from new")
                await self.play_sound(guild_instance)
        elif args[0] == "!play" or args[0] == "!resume":
            if guild_instance.voice_client != None and guild_instance.voice_client.is_connected() and guild_instance.voice_client.is_paused():
                print("attempt to pause")
                guild_instance.voice_client.resume()
        elif args[0] == "!pause":
            if guild_instance.voice_client != None and guild_instance.voice_client.is_connected() and guild_instance.voice_client.is_playing():
                print("attempt to pause")
                guild_instance.voice_client.pause()
                
        elif args[0] == "!quit":
            if guild_instance.voice_client != None and guild_instance.voice_client.is_connected():
                print("attempt to quit")
                self.clear_queue(guild_instance)
                guild_instance.repeat = False
                guild_instance.voice_client.stop()
                await guild_instance.voice_client.disconnect()
        elif args[0] == "!skip":
            if guild_instance.voice_client != None and guild_instance.voice_client.is_connected() and guild_instance.voice_client.is_playing():
                print("attempt to skip")
                guild_instance.repeat = False
                guild_instance.voice_client.stop()
        elif args[0] == "!queue":
            await guild_instance.show_queue(guild_instance, message.channel)
        elif args[0] == "!repeat":
            guild_instance.repeat = not guild_instance.repeat
            self.logger("info", f'Repeat: {self.repeat}')
        elif args[0] == "!clear":
            self.clear_queue(guild_instance)
        elif args[0] == "!log":
            #TODO: add it to the logging channels
            pass
    
    async def clear_queue(self):
        while not self.playlist.empty():
            await self.playlist.get()
            self.playlist.task_done()
    
    async def show_queue(self, guild_instance: GuildInstance,  channel):
            i: int = 1
            msg:str = "```\n"
            if guild_instance.music_playing != None:
                msg += f'Currently Playing: {self.music_playing.title}'
                if guild_instance.repeat:
                    msg += ' (on repeat)'
                msg += '\n'
            #Kinda bad to call that private variable, but I need a quick read-only of the queue. Consider another structure
            for music in guild_instance.playlist._queue:
                msg += f'{i}. {music.title}\n'
                i += 1
            msg += "```"
            print(msg)
            await self.send_message(msg, channel)
        
    async def play_sound(self, guild_instance: GuildInstance):
            while not guild_instance.playlist.empty():
                music_to_play:Music = await guild_instance.playlist.get()
                while not music_to_play.downloaded:
                     await asyncio.sleep(0.5)
                while True:
                    guild_instance.voice_client.play(discord.FFmpegPCMAudio(source=music_to_play.file_name))
                    guild_instance.music_playing = music_to_play
                    print("attempting to play music")
                    while guild_instance.voice_client.is_playing():
                        await asyncio.sleep(0.5)
                    if guild_instance.repeat == False:
                        break
                guild_instance.playlist.task_done()
            print("playlist empty </3")
            guild_instance.music_playing = None
    
    async def get_music(self, urls:list):
        ret = list()
        youtube_urls = list()
        filenames  = list()
        for u in urls:
            m = Music()
            m.youtube_url = u
        
            video_info = yt_dlp.YoutubeDL().extract_info(
                url =  m.youtube_url,download=False
            )
            m.id = video_info['id']
            m.title = video_info['title']
            m.file_name = "music/" + m.id + ".mp3"
            filenames.append(m.file_name)
            if os.path.exists(m.file_name):
                m.downloaded = True
                ret.append(m)
                continue

            youtube_urls.append(video_info['webpage_url'])
            ret.append(m)

        options={
            'format':'bestaudio/best',
            'keepvideo':False,
            'outtmpl': '%(id)s.mp3',
            'paths': {'home': "music/"}
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download(youtube_urls)

        print("Download complete... {}".format(filenames))
        for m in ret:
            m.downloaded = True

        return ret

    #TODO: create a logger
    async def send_message(self, msg:str, channel):
        await channel.send(msg)

    async def logger(self, level, msg:str, channel):
        log_msg = f'**{level}**:\n {msg}'
        print(log_msg)
        await self.send_message(log_msg, channel)

client = TnTRhythmBot()
client.run(token)