js_file = r"c:\Users\Lenovo\Documents\billerq\build-cable\build\static\js\main.c2891d24.js"
with open(js_file, "r", encoding="utf-8") as f:
    content = f.read()

# Print snippet from 20000 to 32000
print(content[20000:32000])
