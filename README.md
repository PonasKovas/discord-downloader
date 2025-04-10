# discord-downloader

Download large chat logs from discord for archiving purposes.

```
usage: main.py [-h] [--token TOKEN] [--channel CHANNEL] [--path PATH] [--batch BATCH]

discord chat log downloader

options:
  -h, --help         show this help message and exit
  --token TOKEN      discord auth token
  --channel CHANNEL  discord channel id
  --path PATH        where to save the logs
  --batch BATCH      how many messages to download in a batch
```

Only `--token` and `--channel` are **required**. The script will produce a zstd compressed chat log, with only text, in the following format:

```
NUL<{USERNAME}>NUL{MESSAGE}NEWLINE
...
```

`NUL` is not normally visible, so it will look like `<User>Hello` for a human, but the `NUL` bytes can be used to actually parse it with code, to not rely on the username not containing `<` or `>`, or the message not containing newlines.

The script can be stopped and resumed at any time. You can also continue downloading the same chat, after already completing it before, as long as there are new messages since then.
