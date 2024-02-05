import os
import random
import requests
import schedule
import threading
import time
import pickle
import subprocess

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

class Screensaver:
    def __init__(self):
        self.running = False
        self.thread = None

    def _run(self):
        # This method runs in a separate thread
        while self.running:
            get_random_photo_and_save()
            time.sleep(120)  # Wait for 2 minutes before fetching the next photo

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run)
            self.thread.start()
            print("Screensaver Service started.")

    def stop(self):
        if self.running:
            self.running = False
            self.thread.join()  # Wait for the thread to finish
            print("Screensaver Service stopped.")

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

def get_service():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('screensaver/token.pickle'):
        with open('screensaver/token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'screensaver/credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        # Save the credentials for the next run
        with open('screensaver/token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('photoslibrary', 'v1', credentials=creds, static_discovery=False)

def download_image(url, filename):
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'wb') as file:
            file.write(response.content)

def get_random_photo_and_save():
    service = get_service()
    
    # List all albums
    albums_result = service.albums().list(pageSize=50).execute()
    albums = albums_result.get('albums', [])
    
    # Find the specific album by its title
    target_album_title = 'PiTouch'  
    target_album_id = None
    for album in albums:
        if album['title'] == target_album_title:
            target_album_id = album['id']
            break
    
    if not target_album_id:
        print(f'Album "{target_album_title}" not found.')
        return
    
    # List media items in the specific album
    search_result = service.mediaItems().search(body={
        'albumId': target_album_id,
        'pageSize': 100
    }).execute()
    
    items = search_result.get('mediaItems', [])
    
    if not items:
        print(f'No items found in album "{target_album_title}".')
    else:
        # Choose a random photo
        photo = random.choice(items)
        filename = f"screensaver/photo.jpg"
        download_image(photo['baseUrl'], filename)
        print(f'Downloaded {filename}')
        displayOnScreen()

def displayOnScreen():
    subprocess.run(['killall feh'], shell=True)
    subprocess.run(['feh --fullscreen --auto-zoom --action1 ";killall feh" --borderless --on-last-slide quit --auto-reload  screensaver//photo.jpg &'], shell=True)



#schedule.every(2).minutes.do(get_random_photo_and_save)
#get_random_photo_and_save()

#while True:
#    schedule.run_pending()
#    time.sleep(1)
    

