#!/usr/bin/env python3
"""Dynablox launcher: обрабатывает ссылки dynablox://startserver|startplayer|playsolo?file=...&id=...&user=...&host=...&port=...
Установка протокола (один раз, Windows):  python launcher.py --install
Структура .rbxm персонажа:              python launcher.py --inspect [файл.rbxm]
Цвета и лицо персонажа:                python launcher.py --customize
Режим строительства:                    python launcher.py --open
Проверка без запуска клиента:            python launcher.py "dynablox://playsolo?file=games/20.rbxl" --dry-run
"""
import sys, os, re, json, subprocess, tempfile
from urllib.parse import urlparse, parse_qs

# ======== НАСТРОЙКА (подгони под свой клиент 2007) ========
BASE = os.path.dirname(os.path.abspath(__file__))
CLIENT_EXE = os.path.join(BASE, "client", "RobloxApp.exe")   # путь к клиенту
SCRIPTS_DIR = os.path.join(BASE, "scripts")                   # StartServer.lua, StartPlayer.lua, PlaySolo.lua
GAMES_DIR = os.path.join(BASE, "games")                       # .rbxl файлы
DEFAULT_PORT = "53640"
# Аргументы клиента для каждого действия. {script} — путь к Lua, {file} — путь к .rbxl.
# ПРОВЕРЬ эти флаги: они должны совпадать с тем, как ты сейчас запускаешь клиент вручную.
ARGS = {
    "startserver": ["-script", "{script}", "{file}"],
    "startplayer": ["-script", "{script}"],
    "playsolo":    ["-script", "{script}", "{file}"],
    # Режим строительства: открываем .rbxl БЕЗ запуска игры (без RunService:run), инструменты берутся из самого клиента.
    "build":       ["{script}", "{file}"],
}
SCRIPTS = {"startserver": "StartServer.lua", "startplayer": "StartPlayer.lua", "playsolo": "PlaySolo.lua", "build": ""}  # "" = без скрипта
# ==========================================================

def safe_game(file_param):
    """Разрешаем только .rbxl/.rbxlx внутри папки games (защита от подстановки путей из ссылки)."""
    if not file_param:
        return ""
    name = os.path.basename(file_param.replace("\\", "/"))
    if not name.lower().endswith((".rbxl", ".rbxlx")):
        sys.exit("Недопустимый тип файла: " + name)
    path = os.path.join(GAMES_DIR, name)
    if not os.path.isfile(path):
        sys.exit("Игра не найдена: " + path)
    return path

# ===== Кастомизация персонажа (цвета и лицо) =====
CHAR_FILE = os.path.join(BASE, "character.json")
DEFAULT_CHAR = {"head": "#f5d7a1", "torso": "#0055bf", "arms": "#f58a1f", "legs": "#287f47", "face": "smile"}
# Классические BrickColor: имя -> RGB. Hex-цвет заменяется ближайшим из них (в клиенте 2007 нет произвольных цветов).
# Если какого-то имени нет в твоей сборке клиента, эта часть просто останется как была.
PALETTE = {
    "Bright red": (196, 40, 28), "Bright blue": (13, 105, 172), "Bright yellow": (245, 205, 48),
    "Black": (27, 42, 53), "White": (242, 243, 243), "Medium stone grey": (163, 162, 165),
    "Dark stone grey": (99, 95, 98), "Bright green": (75, 151, 75), "Dark green": (40, 127, 71),
    "Bright orange": (218, 133, 65), "Brick yellow": (215, 197, 154), "Reddish brown": (105, 64, 40),
    "Bright violet": (107, 50, 124), "Pastel Blue": (128, 187, 219), "Sand blue": (116, 134, 157),
    "Medium red": (218, 134, 122), "Teal": (18, 238, 212), "Nougat": (204, 142, 105),
    "Dark orange": (160, 95, 53), "Br. yellowish green": (164, 189, 71), "Earth green": (39, 70, 45),
}
# Лица: имя -> путь в клиенте. Все png из client/content/textures/faces/ добавляются автоматически.
FACES = {"smile": "rbxasset://textures/face.png"}

def faces():
    f = dict(FACES)
    d = os.path.join(os.path.dirname(CLIENT_EXE), "content", "textures", "faces")
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            stem, ext = os.path.splitext(n)
            if ext.lower() == ".png" and re.fullmatch(r"[A-Za-z0-9_\- ]{1,30}", stem):
                f[stem] = "rbxasset://textures/faces/" + n
    return f

def nearest_brick(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return min(PALETTE, key=lambda k: (PALETTE[k][0]-r)**2 + (PALETTE[k][1]-g)**2 + (PALETTE[k][2]-b)**2)

def load_char(q=None):
    """character.json (задаётся в лаунчере) -> перекрывается параметрами из ссылки (с сайта)."""
    ch = dict(DEFAULT_CHAR)
    try:
        ch.update({k: v for k, v in json.load(open(CHAR_FILE, encoding="utf-8")).items() if k in ch})
    except Exception:
        pass
    for k in ch:
        v = (q or {}).get(k, "")
        if k == "face":
            if v in faces(): ch[k] = v
        elif re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
            ch[k] = "#" + v.lstrip("#")
    return ch

def lua_customize(ch):
    col = {k: nearest_brick(ch[k]) for k in ("head", "torso", "arms", "legs")}
    face = faces().get(ch["face"], "")
    return """
-- [dynablox customize]
do
  local COL = {head="%(head)s", torso="%(torso)s", arms="%(arms)s", legs="%(legs)s"}
  local FACE = "%(face)s"
  local plr = game.Players.LocalPlayer
  local function paint(char)
    local function set(name, color)
      local part = char:findFirstChild(name)
      if part then pcall(function() part.BrickColor = BrickColor.new(color) end) end
    end
    set("Head", COL.head) set("Torso", COL.torso)
    set("Left Arm", COL.arms) set("Right Arm", COL.arms)
    set("Left Leg", COL.legs) set("Right Leg", COL.legs)
    local head = char:findFirstChild("Head")
    if head and FACE ~= "" then
      local face = head:findFirstChild("face")
      if face then pcall(function() face.Texture = FACE end) end
    end
  end
  local function waitPaint()
    for i = 1, 50 do
      local c = plr.Character
      if c and c:findFirstChild("Head") and c:findFirstChild("Torso") then paint(c) return end
      wait(0.1)
    end
  end
  if plr then
    plr.Changed:connect(function(p) if p == "Character" then waitPaint() end end)
    waitPaint()
  end
end
""" % dict(col, face=face)

PENDING_FACE = None

def apply_face(name):
    """Подмена content/textures/face.png выбранным лицом из content/textures/faces/<имя>.png.
    Оригинал один раз сохраняется как face.orig.png и возвращается для лица 'smile'."""
    import shutil
    tex = os.path.join(os.path.dirname(CLIENT_EXE), "content", "textures")
    target, orig = os.path.join(tex, "face.png"), os.path.join(tex, "face.orig.png")
    try:
        if os.path.isfile(target) and not os.path.isfile(orig):
            shutil.copy2(target, orig)
        src = orig if name == "smile" else os.path.join(tex, "faces", name + ".png")
        if os.path.isfile(src):
            shutil.copy2(src, target)
    except OSError as e:
        print("Не удалось сменить лицо:", e)

def with_customization(script, q, action):
    global PENDING_FACE
    PENDING_FACE = load_char(q)["face"]
    src = open(script, encoding="utf-8").read() + "\n" + lua_customize(load_char(q))
    tmp = os.path.join(tempfile.gettempdir(), "dynablox_%s_c.lua" % action)
    open(tmp, "w", encoding="utf-8").write(src)
    return tmp

def customize_gui():
    """Окно выбора цветов и лица. Сохраняет character.json, применяется при каждом запуске игры."""
    import tkinter as tk
    from tkinter import colorchooser, ttk
    ch = load_char()
    root = tk.Tk(); root.title("Dynablox: Customize")
    swatches = {}
    def pick(k):
        c = colorchooser.askcolor(color=ch[k], title=k)[1]
        if c: ch[k] = c; swatches[k].config(bg=c)
    for i, k in enumerate(("head", "torso", "arms", "legs")):
        tk.Label(root, text=k.capitalize(), width=8, anchor="w").grid(row=i, column=0, padx=8, pady=3)
        swatches[k] = tk.Button(root, width=10, bg=ch[k], command=lambda k=k: pick(k))
        swatches[k].grid(row=i, column=1, padx=8)
    tk.Label(root, text="Face", width=8, anchor="w").grid(row=4, column=0, padx=8, pady=3)
    face = ttk.Combobox(root, values=list(faces()), state="readonly", width=12); face.set(ch["face"]); face.grid(row=4, column=1)
    def save():
        ch["face"] = face.get() or "smile"
        json.dump(ch, open(CHAR_FILE, "w", encoding="utf-8"), indent=2)
        root.destroy()
    tk.Button(root, text="Save", command=save).grid(row=5, column=0, columnspan=2, pady=8)
    root.mainloop()

def inspect_rbxm(path=None):
    """Печатает структуру .rbxm/.rbxl (классы, имена, цвета, текстуры). Результат можно скопировать в чат."""
    import xml.etree.ElementTree as ET
    path = path or os.path.join(os.path.dirname(CLIENT_EXE), "content", "fonts", "character.rbxm")
    def tree(el, depth=0):
        if el.tag == "Item":
            name, extra = "", []
            props = el.find("Properties")
            if props is not None:
                for p in props:
                    n, text = p.get("name"), "".join(p.itertext()).strip()
                    if n == "Name": name = text
                    elif n in ("BrickColor", "Texture", "HeadColor", "TorsoColor", "LeftArmColor", "RightArmColor", "LeftLegColor", "RightLegColor"):
                        extra.append("%s=%s" % (n, text))
            print("  " * depth + "%s '%s' %s" % (el.get("class"), name, " ".join(extra)))
            depth += 1
        for c in el:
            if c.tag == "Item": tree(c, depth)
    data = open(path, "rb").read()
    print("Файл: %s, %d байт, начало: %r" % (path, len(data), data[:16]))
    try:
        tree(ET.fromstring(data))
    except ET.ParseError:
        print("Это не XML. Найденные строки (возможные имена объектов):")
        seen = []
        for m in re.findall(rb"[A-Za-z][A-Za-z0-9 _.\-]{2,30}", data):
            t = m.decode("ascii")
            if t not in seen: seen.append(t)
        print(", ".join(seen[:120]))

def pick_file():
    """Диалог выбора любого .rbxl с диска (для режима строительства)."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw()
    path = filedialog.askopenfilename(title="Открыть место", initialdir=GAMES_DIR,
                                      filetypes=[("Roblox place", "*.rbxl *.rbxlx")])
    root.destroy()
    if not path:
        sys.exit("Файл не выбран")
    return path

def build(url):
    u = urlparse(url)
    action = (u.netloc or u.path).strip("/").lower()
    if action not in SCRIPTS:
        sys.exit("Неизвестное действие: " + action)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    script = os.path.join(SCRIPTS_DIR, SCRIPTS[action]) if SCRIPTS[action] else ""
    if action == "startplayer":      # подставляем адрес/порт сервера в копию скрипта
        host = "".join(c for c in q.get("host", "localhost") if c.isalnum() or c in ".-")
        port = q.get("port", DEFAULT_PORT)
        port = port if port.isdigit() else DEFAULT_PORT
        src = open(script, encoding="utf-8").read().replace('"localhost"', '"%s"' % host).replace(DEFAULT_PORT, port)
        tmp = os.path.join(tempfile.gettempdir(), "dynablox_StartPlayer.lua")
        open(tmp, "w", encoding="utf-8").write(src)
        script = tmp
    if action in ("playsolo", "startplayer"):   # применяем цвета и лицо персонажа
        script = with_customization(script, q, action)
    game = safe_game(q.get("file", "")) if action != "startplayer" else ""
    if action == "build" and not game:
        game = pick_file()
    args = [a.format(script=script, file=game) for a in ARGS[action]]
    return [CLIENT_EXE] + [a for a in args if a]

def install():
    import winreg
    cmd = '"%s" "%s" "%%1"' % (sys.executable, os.path.abspath(__file__))
    root = r"Software\Classes\dynablox"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as k:
        winreg.SetValue(k, "", winreg.REG_SZ, "URL:Dynablox Protocol")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root + r"\shell\open\command") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, cmd)
    print("Готово: протокол dynablox:// зарегистрирован.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--inspect":     # python launcher.py --inspect [файл.rbxm]
        inspect_rbxm(sys.argv[2] if len(sys.argv) > 2 else None); sys.exit(0)
    if sys.argv[1] == "--customize":
        customize_gui(); sys.exit(0)
    if sys.argv[1] == "--open":      # python launcher.py --open  -> выбрать .rbxl и открыть в режиме строительства
        sys.argv[1] = "dynablox://build"
    if sys.argv[1] == "--install":
        install()
    else:
        cmd = build(sys.argv[1])
        if "--dry-run" in sys.argv:
            print(cmd)
        else:
            if PENDING_FACE:
                apply_face(PENDING_FACE)
            subprocess.Popen(cmd, cwd=os.path.dirname(CLIENT_EXE))
