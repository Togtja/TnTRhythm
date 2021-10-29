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

token  = open('token.txt', 'r').read()
class TnTRhythmBot(discord.Client):
    def __init__(self, *, loop=None, **options):
        super().__init__(loop=loop, **options)
        self.voice_client: VoiceClient  = None
        self.playlist:asyncio.Queue = asyncio.Queue()
        self.music_playing: Music = None
        self.repeat = False
    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
    
    async def add_to_queue(self, songs):
        print("added to queue", songs)
        for music in await self.get_music(songs):
            await self.playlist.put(item=music)

    async def on_message(self, message: discord.message.Message):
        #print(type(message.author))
        if message.author == self.user:
            return

        args = message.content.split(" ")
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
            await self.add_to_queue(args[1:])
            if(self.voice_client != None and self.voice_client.is_connected()):
                if self.voice_client.is_playing():
                    return
                print("playing from existing")
                await self.play_sound()
            else:
                self.voice_client = await v_c.connect()
                print("Play from new")
                await self.play_sound()
        elif args[0] == "!play" or args[0] == "!resume":
            if self.voice_client != None and self.voice_client.is_connected() and self.voice_client.is_paused():
                print("attempt to pause")
                self.voice_client.resume()
        elif args[0] == "!pause":
            if self.voice_client != None and self.voice_client.is_connected() and self.voice_client.is_playing():
                print("attempt to pause")
                self.voice_client.pause()
                
        elif args[0] == "!quit":
            if self.voice_client != None and self.voice_client.is_connected():
                print("attempt to quit")
                self.clear_queue()
                self.repeat = False
                self.voice_client.stop()
                await self.voice_client.disconnect()
        elif args[0] == "!skip":
            if self.voice_client != None and self.voice_client.is_connected() and self.voice_client.is_playing():
                print("attempt to skip")
                self.repeat = False
                self.voice_client.stop()
        elif args[0] == "!queue":
            await self.show_queue(message.channel)
        elif args[0] == "!repeat":
            self.repeat = not self.repeat
            self.logger("info", f'Repeat: {self.repeat}')
        elif args[0] == "!clear":
            self.clear_queue()
        elif args[0] == "!log":
            #TODO: add it to the logging channels
            pass
    
    async def clear_queue(self):
        while not self.playlist.empty():
            await self.playlist.get()
            self.playlist.task_done()
    
    async def show_queue(self, channel):
            i: int = 1
            msg:str = "```\n"
            if self.music_playing != None:
                msg += f'Currently Playing: {self.music_playing.title}'
                if self.repeat:
                    msg += ' (on repeat)'
                msg += '\n'
            #Kinda bad to call that private variable, but I need a quick read-only of the queue. Consider another structure
            for music in self.playlist._queue:
                msg += f'{i}. {music.title}\n'
                i += 1
            msg += "```"
            print(msg)
            await self.send_message(msg, channel)
        
    async def play_sound(self):
            while not self.playlist.empty():
                music_to_play:Music = await self.playlist.get()
                while not music_to_play.downloaded:
                     await asyncio.sleep(0.5)
                while True:
                    self.voice_client.play(discord.FFmpegPCMAudio(source=music_to_play.file_name))
                    self.music_playing = music_to_play
                    print("attempting to play music")
                    while self.voice_client.is_playing():
                        await asyncio.sleep(0.5)
                    if self.repeat == False:
                        break
                self.playlist.task_done()
            print("playlist empty </3")
            self.music_playing = None
    
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
        log_msg = f'**{level}:\n {msg}'
        print(log_msg)
        await self.send_message(log_msg, channel)

client = TnTRhythmBot()
client.run(token)