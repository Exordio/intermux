# InterMux

Утилита для Linux, которая запускает приложение так, чтобы весь его сетевой трафик шёл через выбранный сетевой интерфейс. Например, браузер через Wi-Fi, а торрент-клиент через USB-модем или Ethernet.

Это форк [Rishi-Bhati/intermux](https://github.com/Rishi-Bhati/intermux). Работает только под Linux, поддержка Windows в этом форке не планируется. Был проведен реверт для отмены поддержки винды. 

## Принцип работы

Для каждого выбранного интерфейса InterMux создаёт отдельное сетевое пространство имён (network namespace) и запускает приложение внутри него:

1. Создаётся namespace `ns_<hash>`, где `<hash>` — первые 8 символов MD5 от имени интерфейса.
2. Пара veth (`veth0_<hash>` / `veth1_<hash>`) соединяет namespace с основной системой. Namespace получает подсеть `10.0.N.0/24`, где N вычисляется из того же хэша.
3. На хосте включается `net.ipv4.ip_forward`, добавляется правило `MASQUERADE` для этой подсети на выбранный интерфейс и правило `FORWARD -j ACCEPT`.
4. Policy routing: для подсети namespace создаётся отдельная таблица маршрутизации (201–453) с маршрутом по умолчанию через шлюз выбранного интерфейса и правило `ip rule from 10.0.N.0/24`. Без этого шага трафик уходил бы через основной маршрут системы.
5. В `/etc/netns/ns_<hash>/resolv.conf` записываются реальные DNS-серверы. Заглушка `127.0.0.53` от `systemd-resolved` внутри namespace не работает, поэтому адреса берутся из `resolvectl dns` или `/etc/resolv.conf`.
6. Приложение запускается через `ip netns exec ... sudo -u <пользователь>`, то есть от имени обычного пользователя, а не root. В окружение передаются `DISPLAY`/`WAYLAND_DISPLAY`, `XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`, сокеты PulseAudio/PipeWire и `HOME`, поэтому приложение видит ваш профиль, графическую сессию и звук.

Права root нужны только для настройки сети (шаги 1–5).

## Требования

- Linux с поддержкой network namespaces (`CONFIG_NET_NS`, есть во всех распространённых дистрибутивах)
- Python 3 с модулем `tkinter` (нужен только для GUI)
- `iproute2`, `iptables`, `sudo`
- `pkexec` (polkit) — для повышения прав из GUI; без него используется `sudo`
- `xhost` — для доступа GUI, запущенного от root, к X-серверу
- X11 или Wayland с XWayland (интерфейс написан на Tk)

Сторонние Python-пакеты не нужны: код использует только стандартную библиотеку.

### Установка зависимостей

Debian / Ubuntu / Mint:

```bash
sudo apt install python3 python3-tk iproute2 iptables sudo pkexec x11-xserver-utils
```

На старых версиях Debian/Ubuntu вместо `pkexec` используйте пакет `policykit-1`.

Arch / Manjaro / EndeavourOS:

```bash
sudo pacman -S python tk iproute2 iptables sudo polkit xorg-xhost
```

Fedora / RHEL / Rocky:

```bash
sudo dnf install python3 python3-tkinter iproute iptables sudo polkit xhost
```

openSUSE:

```bash
sudo zypper install python3 python3-tk iproute2 iptables sudo polkit xhost
```

### Получение исходников

```bash
git clone https://github.com/Exordio/intermux.git
cd intermux
sudo python3 cli.py check
```

`check` показывает, каких системных утилит не хватает, и как их установить.

## Использование

### GUI

```bash
python3 gui/app.py
```

Запускать можно от обычного пользователя: программа сама перезапустится с правами root через `pkexec` или, если его нет, через `sudo -E`.

Порядок работы:

1. Выберите интерфейс в списке. Виртуальные интерфейсы (`veth`, `docker`, `br-`, `tun`, `tap`, `virbr`, `vmnet`, `vboxnet`) скрыты, нажмите «Refresh», чтобы обновить список.
2. Введите имя команды из `PATH` (например, `firefox`) или полный путь к исполняемому файлу и нажмите «Add».
3. Нажмите «Assign», и все приложения из списка Pending будут запущены.

Кнопки:

- «Clear All» очищает списки и удаляет таблицы маршрутизации `*_rt`.
- «Reset Everything» удаляет veth-интерфейсы, namespace, правила policy routing, таблицы 201–453 и правила `MASQUERADE`, созданные InterMux.

Если приложение уже запущено, будет предложено закрыть его и запустить заново через выбранный интерфейс, открыть второй экземпляр с отдельным профилем или отменить запуск.

`gui/gui.py` — старое окно со списком интерфейсов. Кнопка «Create routing tables» в нём просто открывает `gui/app.py`.

### CLI

Все команды CLI требуют root.

```bash
# Список активных интерфейсов с IP-адресами и шлюзами
sudo python3 cli.py list

# Запустить приложение через указанный интерфейс
sudo python3 cli.py assign --app firefox --iface wlan0

# Проверить системные зависимости
sudo python3 cli.py check

# Удалить таблицы маршрутизации *_rt из rt_tables
sudo python3 cli.py clear

# Удалить namespace, созданные для активных интерфейсов
sudo python3 cli.py reset
```

Если приложение уже запущено, `assign` спросит, что делать:

```
[!] 'firefox' is already running (PID(s): [12345]).
    Options:
    1) Close current instance and reopen on the selected network (uses your default profile)
    2) Open a new instance with a separate profile
    3) Cancel
    Enter choice [1/2/3]:
```

## Firefox

- Если Firefox не запущен или выбран вариант «закрыть и открыть заново», используется ваш основной профиль.
- Если выбран второй экземпляр, создаётся отдельный постоянный профиль `~/.mozilla/firefox/intermux-<интерфейс>`. Закладки, cookie и расширения основного профиля в нём недоступны.
- Вариант «закрыть и открыть заново» сначала отправляет `SIGTERM` всем процессам, в командной строке которых встречается имя приложения, а через 1,5 секунды — `SIGKILL`. Firefox может не успеть корректно завершиться, поэтому восстановление сессии не гарантируется.

## Ограничения

- **Одно приложение на интерфейс.** При каждом назначении namespace для интерфейса пересоздаётся. Приложение, запущенное через этот интерфейс ранее, теряет сеть.
- **Только IPv4.** Переадресация и NAT настраиваются только для IPv4, в namespace нет IPv6.
- **CLI не настраивает policy routing** (шаг 4 выше) и выбирает подсеть через `hash()`, который меняется между запусками. Через CLI надёжно работает только интерфейс, через который и так идёт основной маршрут системы. Для остальных используйте GUI.
- **Сброс неполный.** Правило `iptables -A FORWARD -j ACCEPT` добавляется при каждом назначении и не удаляется ни одним из вариантов сброса; `net.ipv4.ip_forward` тоже остаётся включённым. `cli.py reset` не удаляет правила `iptables` и policy routing — для этого используйте «Reset Everything» в GUI. После перезагрузки namespace, маршруты и правила `iptables` исчезают, но записи в `rt_tables` и каталоги `/etc/netns/ns_*` остаются.
- **Chromium** запрещён в коде: по словам автора оригинального проекта, его песочница конфликтует с network namespaces. Другие браузеры на базе Chromium (Chrome, Brave и т. д.) не блокируются, но их работа не проверялась.
- Namespace изолирует только сеть. Файлы, процессы и права пользователя остаются общими с системой, поэтому как средство безопасности это не годится.

## Структура проекта

```
intermux/
├── cli.py                  # Консольный интерфейс
├── core/
│   ├── interface.py        # Обнаружение интерфейсов через ip
│   ├── router.py           # Таблицы маршрутизации в rt_tables
│   └── platform_utils.py   # Дистрибутив, пользователь, окружение сессии, DNS, зависимости
├── gui/
│   ├── app.py              # Основной GUI (Tk)
│   └── gui.py              # Старое окно со списком интерфейсов
├── release_notes.md
└── license
```

## Настройка

Номера таблиц маршрутизации для интерфейсов (`<iface>_rt`) задаются в `core/router.py`:

```python
BASE_TABLE_ID = 100   # номер первой таблицы
BASE_PRIORITY = 1000  # приоритет ip rule = BASE_PRIORITY + номер таблицы
```

Таблицы для подсетей namespace (`200 + N`) и их приоритеты (`500 + N`) заданы в `gui/app.py`, в функции `assign()`.

Файл `rt_tables` ищется в `/etc/iproute2/rt_tables`, затем в `/usr/share/iproute2/rt_tables`.

## Диагностика

GUI ведёт подробный лог (уровень DEBUG, со стектрейсами) в `~/.local/share/intermux/intermux.log` того пользователя, от имени которого работает процесс. После повышения прав это обычно root, то есть `/root/.local/share/intermux/intermux.log`. CLI пишет только в консоль.

Если интерфейс не отображается, проверьте, что он поднят и у него есть IP-адрес:

```bash
ip addr show
sudo ip link set <интерфейс> up
```

Если в приложении нет интернета:

```bash
sudo python3 cli.py check
sysctl net.ipv4.ip_forward               # должно быть 1
sudo iptables -t nat -S POSTROUTING      # должно быть правило MASQUERADE для 10.0.N.0/24
ip rule show                             # должно быть правило from 10.0.N.0/24
sudo ip netns exec ns_<hash> ping -c1 1.1.1.1
```

Если GUI не запускается на Wayland, проверьте, что установлен XWayland (`xorg-xwayland` в Arch, `xwayland` в Debian/Ubuntu).

## Лицензия

MIT, см. [license](license). Исходный код: Rishi Bhati, 2025.
