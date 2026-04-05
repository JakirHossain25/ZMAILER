# generate_token.py
from google_auth_oauthlib.flow import InstalledAppFlow
import pickle

SCOPES = ['https://www.googleapis.com/auth/gmail.send', 
          'https://www.googleapis.com/auth/gmail.modify']

def generate_token():
    flow = InstalledAppFlow.from_client_secrets_file(
        'client_secret.json', SCOPES)
    creds = flow.run_local_server(port=0)
    
    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)
    
    print("✅ token.pickle generated successfully!")

if __name__ == '__main__':
    generate_token()