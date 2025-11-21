#!/bin/bash
# deploy.sh - автоматическая установка бота

set -e

echo "🚀 Начинаем установку Telegram бота..."

# Обновление системы
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git

# Создание пользователя
if ! id "telegrambot" &>/dev/null; then
    adduser --gecos "" --disabled-password telegrambot
    usermod -aG sudo telegrambot
fi

# Клонирование репозитория
su - telegrambot -c "
cd /home/telegrambot
if [ -d \"SellerSCbase_bot\" ]; then
    echo 'Обновляем существующую установку...'
    cd SellerSCbase_bot
    git pull
else
    echo 'Клонируем репозиторий...'
    git clone https://github.com/stgm5377-a11y/SellerSCbase_bot.git
    cd SellerSCbase_bot
fi

# Настройка виртуального окружения
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt || pip install python-telegram-bot

# Создание .env
echo 'BOT_TOKEN=8596110238:AAGAekduXEgGRnOmlmu-ZnI-GfNbKl8EzSI' > .env
"

# Настройка systemd службы
cat > /etc/systemd/system/telegram-bot.service << 'EOF'
[Unit]
Description=Telegram Seller Bot
After=network.target

[Service]
Type=simple
User=telegrambot
WorkingDirectory=/home/telegrambot/SellerSCbase_bot
Environment=PATH=/home/telegrambot/SellerSCbase_bot/venv/bin
Environment=BOT_TOKEN=8596110238:AAGAekduXEgGRnOmlmu-ZnI-GfNbKl8EzSI
ExecStart=/home/telegrambot/SellerSCbase_bot/venv/bin/python bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Запуск службы
systemctl daemon-reload
systemctl enable telegram-bot
systemctl start telegram-bot

echo "✅ Бот успешно установлен и запущен!"
echo "📊 Проверка статуса: systemctl status telegram-bot"
echo "📋 Просмотр логов: journalctl -u telegram-bot -f"