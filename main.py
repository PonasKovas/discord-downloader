import asyncio
import discord
import argparse
import sys
import signal
from pathlib import Path
import struct
import zstandard as zstd
import datetime

parser = argparse.ArgumentParser(description="discord chat log downloader")
parser.add_argument('--token', type=str, help='discord auth token')
parser.add_argument('--channel', type=int, help='discord channel id')
parser.add_argument('--path', type=str, help='where to save the logs')
parser.add_argument('--batch', type=int,
                    help='how many messages to download in a batch', default=100)
args = parser.parse_args()


shutdown_event = asyncio.Event()
in_critical_section = False


def handle_signal():
    if in_critical_section:
        print("Received signal but in critical section. Waiting...")
        shutdown_event.set()
    else:
        print("Received signal, exiting.")
        sys.exit(0)


def get_file_path(channel_name: str) -> Path:
    if args.path is None:
        file_path = Path(f"{channel_name}.zst")
    else:
        file_path = Path(f"{args.path}")

    return file_path


# 3 u64s. 1. Last read message 2. Count of read messages 3. Uncompressed chat size in bytes
METADATA_SIZE = 3 * 8
MAGIC_ZSTD_HEADER = b'\x50\x2A\x4D\x18'


def read_metadata(file_path):
    with open(file_path, 'rb') as file:
        # Read the magic header
        magic_header = file.read(4)
        if magic_header != MAGIC_ZSTD_HEADER:
            raise ValueError("Not a valid skippable frame format.")

        frame_length = struct.unpack('<I', file.read(4))[0]
        if frame_length != METADATA_SIZE:
            raise ValueError("Invalid metadata size")

        # Read the fixed-size frame
        frame_data = file.read(METADATA_SIZE)

        # Unpack the u64 values (big-endian)
        # 'Q' is for unsigned 64-bit integers
        u64_values = struct.unpack('<3Q', frame_data)
        return u64_values


def overwrite_metadata(file_path, new_data):
    with open(file_path, 'r+b') as file:
        # Read the magic header
        magic_header = file.read(4)
        if magic_header != MAGIC_ZSTD_HEADER:
            raise ValueError("Not a valid skippable frame format.")

        frame_length = struct.unpack('<I', file.read(4))[0]
        if frame_length != METADATA_SIZE:
            raise ValueError("Invalid metadata size")

        # Move to the beginning of the frame (after the magic header and length)
        file.seek(8)

        # Pack the new data as u64 integers and overwrite the frame
        frame_data = struct.pack('<3Q', *new_data)
        file.write(frame_data)


def initialize_metadata(file_path):
    with open(file_path, 'wb') as file:
        # Write the magic header
        file.write(MAGIC_ZSTD_HEADER)

        # Write the length of the frame
        file.write(struct.pack('<I', METADATA_SIZE))

        # Initialize the frame data (3 u64 integers, all set to 0)
        frame_data = struct.pack('>3Q', 0, 0, 0)

        file.write(frame_data)


def append_batch(file_path, text):
    # Open the zstd file in append mode
    with open(file_path, 'ab') as file:
        # Initialize a zstd compressor
        compressor = zstd.ZstdCompressor(level=22)

        # Encode the text as bytes
        text_bytes = text.encode('utf-8')

        # Compress the text
        compressed_data = compressor.compress(text_bytes)

        # Append the compressed data to the zstd file
        file.write(compressed_data)


class MessageId:
    def __init__(self, id):
        self.id = id
        self.type = discord.MessageType


class DiscordDownloader(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, handle_signal)
        loop.add_signal_handler(signal.SIGTERM, handle_signal)

        # obtain the needed channel
        channel = self.get_channel(int(args.channel))
        if channel is None:
            print(f"channel not found.")
            sys.exit(1)

        if hasattr(channel, "name"):
            channel_name = channel.name
        else:
            channel_name = channel.recipient.name

        file_path = get_file_path(channel_name)
        print(f"operating on {file_path}")

        if not file_path.exists():
            # initialize empty
            print("Partial data not found, starting a new download!")
            initialize_metadata(file_path)

        last_read_message, total_messages_read, uncompressed_size = read_metadata(
            file_path)
        if last_read_message == 0:
            last_read_message = None

        print(f"INFO:\nLast read message: {last_read_message}\nTotal messages read: {total_messages_read}\nTotal uncompressed size: {uncompressed_size} bytes")

        # Start reading the chat logs
        while True:
            if last_read_message is None:
                after = None
            else:
                after = MessageId(last_read_message)

            messages = [message async for message in channel.history(limit=args.batch, after=after, oldest_first=True)]

            if len(messages) == 0:
                break

            formatted_log = ""
            for message in messages:
                if len(message.content) != 0:
                    # NUL < {USERNAME} > NUL {MESSAGE} NEWLINE
                    formatted_log += f"\0<{message.author.display_name}>\0{message.content}\n"

            # Write to the file
            last_read_message = messages[-1].id
            total_messages_read += len(messages)
            uncompressed_size += len(formatted_log)

            global in_critical_section
            in_critical_section = True

            overwrite_metadata(
                file_path, [last_read_message, total_messages_read, uncompressed_size])
            append_batch(file_path, formatted_log)

            in_critical_section = False
            if shutdown_event.is_set():
                print("Shutdown was requested. Exiting now.")
                sys.exit(0)

            print(f"Batch read. TOTAL MESSAGES: {total_messages_read}, TOTAL UNCOMPRESSED SIZE: {uncompressed_size} bytes")

            if len(messages) < args.batch:
                break

        print(f"FINISHED DOWNLOADING! TOTAL MESSAGES: {total_messages_read}, TOTAL UNCOMPRESSED SIZE: {uncompressed_size} bytes")
        await self.close()
        sys.exit(0)


client = DiscordDownloader()
client.run(args.token)
