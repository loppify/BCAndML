# ADR-0001: EVM platform for device audit

- **Статус:** прийнято.
- **Контекст:** проєкт вимагає Solidity, три взаємопов'язані контракти, локальні тести й Sepolia deployment у ЛР 2.
- **Варіанти:** Ethereum/Hardhat, Polygon PoS, Hyperledger Fabric.
- **Рішення:** реалізувати контракти Solidity для EVM, тестувати на Hardhat local, перевірити deployment на Sepolia.
- **Наслідки:** інструменти й бібліотеки широко доступні; Hardhat локально не моделює розподілений консенсус, а Sepolia не є production-середовищем.
