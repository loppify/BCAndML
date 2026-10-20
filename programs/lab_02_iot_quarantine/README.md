# Лабораторна робота № 2: блокчейн-частина IoT IDS

Індивідуальний прототип для теми № 28. Віртуальні IoT-пристрої реєструються в `DeviceRegistry`, permissions керуються через `AccessControl`, а рішення oracle-заглушки та переходи до карантину журналюються в `DeviceQuarantine`.

## Передумови

- Node.js 22 та npm.
- Інтернет і Sepolia ETH потрібні лише для публічного тестнет-розгортання.

## Локальний запуск

```bash
npm ci
npm test
npm run coverage
npm run demo:local
npm run integrity
```

`demo:local` розгортає систему в локальному Hardhat EVM, створює два virtual devices, надає time-limited доступ, записує normal та attack flow, обчислює SHA-256 для файлів і демонструє виявлення підміни. Наприкінці сценарію пристрій атаки перебуває в карантині. `npm run integrity` окремо підтверджує, що зміна вмісту змінює SHA-256.

## Sepolia

```bash
cp .env.example .env
# заповнити SEPOLIA_RPC_URL та DEPLOYER_PRIVATE_KEY
npm run deploy:sepolia
npm run seed:sepolia
npm run scenario:sepolia
# ETHERSCAN_API_KEY потрібен лише для верифікації контрактів
npm run verify:sepolia
```

`.env` не комітиться. Вихідні адреси, транзакції та хеші зберігаються у `deployments/` і `artifacts/`.

## Ключові команди

- `npm test`: unit, integration, negative і time-dependent тести.
- `npm run coverage`: line/branch coverage.
- `npm run slither`: статичний аналіз через Slither (потрібні `slither-analyzer` і `solc-select`, активний solc 0.8.28).
- `npm run gas`: gas reporter для state-changing функцій.
- `npm run demo:local`: повний відтворюваний сценарій без інтерфейсу.
