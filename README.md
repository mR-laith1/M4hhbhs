# M4hhbhs
import concurrent.futures
import random
import time
import requests

print('M4hhbhsTool - TikTok Accelerated Version without Proxy')

def generate_username(length=4):
    chars = '0987654321qazxswedcfrtgvbuyujniolp'
    return ''.join(random.choices(chars, k=length))

def check_user(user):
    try:
        url = f"https://www.tiktok.com/@{user}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            if "Couldn't find this account" in response.text:
                return f'BAD USER | {user}'
            else:
                return f'GOOD USER | {user}'
        elif response.status_code == 404:
            return f'BAD USER | {user}'
        else:
            return f'ERROR | {user} | HTTP {response.status_code}'
            
    except Exception as e:
        return f'ERROR | {user} | {str(e)}'

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    while True:
        users = [generate_username() for _ in range(5)]
        futures = [executor.submit(check_user, user) for user in users]
        for future in concurrent.futures.as_completed(futures):
            print(future.result())
        time.sleep(5)
