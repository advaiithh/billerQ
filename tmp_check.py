import re

with open(r'C:\Users\Lenovo\Documents\billerq\build\static\js\main.c2891d24.js', 'r', encoding='utf-8') as f:
    c = f.read()

print("File size:", len(c))

# Find login storage key
idx = c.find('"login"')
print(f'\n"login" key at: {idx}')
if idx >= 0:
    print(c[max(0,idx-200):idx+500])

print('\n---d.url pattern---')
idx2 = c.find('d.url')
print(f'd.url at: {idx2}')
if idx2 >= 0:
    print(c[max(0,idx2-100):idx2+400])

print('\n---localStorage---')
idx3 = c.find('localStorage')
print(f'localStorage at: {idx3}')
if idx3 >= 0:
    print(c[max(0,idx3-50):idx3+300])

# Find the API host URL
print('\n---API URL patterns---')
for pattern in ['admin.billerq.com', 'billerq.com/api', '/public/api', 'apiUrl', 'api_url']:
    i = c.find(pattern)
    if i >= 0:
        print(f'Found "{pattern}" at {i}:')
        print(c[max(0,i-50):i+200])
        print()
