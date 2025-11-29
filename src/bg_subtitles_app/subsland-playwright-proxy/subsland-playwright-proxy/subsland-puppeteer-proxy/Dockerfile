FROM node:20-slim

# Install dependencies
RUN apt-get update && apt-get install -y wget gnupg ca-certificates fonts-liberation libatk-bridge2.0-0 libnss3 libxkbcommon0 libxcomposite1 libxrandr2 libxi6 libxcursor1 libxdamage1 libxext6 libxfixes3 libdrm2 libgbm1 libasound2 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev
COPY server.js .

EXPOSE 8080
CMD ["node", "server.js"]
