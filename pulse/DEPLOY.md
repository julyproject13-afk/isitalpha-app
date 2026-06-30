# Деплой Pulse на Koara (193.5.251.72) — через VNC-консоль (SSH у владельца блокируется)

> Урок: VNC-вставка теряет Shift → команды НАБИРАТЬ руками, на сервере сделать `loadkeys us`.
> Секрет-токены НИКОГДА не в git/чат — владелец вписывает их на сервере вручную.

## 1. Код на сервер (git-по-HTTPS, как для isitalpha)
Pulse едет в публичном репо isitalpha-app (папка pulse/), БЕЗ секретов.
На сервере:
```
cd /opt
git clone https://github.com/julyproject13-afk/isitalpha-app.git pulse-src   # или git pull, если уже есть
mkdir -p /opt/pulse
cp /opt/pulse-src/pulse/pulse.py /opt/pulse/
cp /opt/pulse-src/pulse/PULSE_CONTEXT.md /opt/pulse/
cp /opt/pulse-src/pulse/pulse.service /etc/systemd/system/pulse.service
```

## 2. Секреты (владелец вписывает ВРУЧНУЮ на сервере)
```
nano /opt/pulse/bootstrap.env
```
вписать (значения у владельца — токен из @BotFather, ключ Anthropic):
```
PULSE_TG_TOKEN=8xxxxxxxxx:AAH......
ANTHROPIC_API_KEY=sk-ant-api03-......
OWNER_CHAT_ID=
```
сохранить (Ctrl+O, Enter, Ctrl+X), затем:
```
chmod 600 /opt/pulse/bootstrap.env
```

## 3. Запуск
```
systemctl daemon-reload
systemctl enable --now pulse
systemctl status pulse        # должно быть active (running)
```

## 4. Узнать OWNER_CHAT_ID (один раз)
- В Telegram написать своему боту "привет".
- Бот ответит: "Твой chat_id: 12345678".
- Вписать это число в bootstrap.env как OWNER_CHAT_ID:
```
nano /opt/pulse/bootstrap.env   # вписать OWNER_CHAT_ID=12345678
systemctl restart pulse
```
- Теперь бот отвечает ТОЛЬКО владельцу.

## 5. Тест (критично)
1. Написать боту "привет" → отвечает (через Claude).
2. Спросить про проект → отвечает по контексту.
3. `reboot` сервера → `systemctl status pulse` снова active (systemd enable).
4. Выключить Mac → бот всё равно отвечает (он на сервере). ✅ 24/7.

## Логи
```
tail -f /var/log/pulse.log
```
