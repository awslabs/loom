# 2. Usar PostgreSQL como banco relacional, compartilhado com o Keycloak

- **Status:** Aceita
- **Data:** 2026-09-12
- **Decisores:** Mantenedores da plataforma
- **Relacionada a:** [ADR 0001 — Usar Keycloak como provedor de identidade na versão inicial](0001-keycloak-as-identity-provider.md)

## Contexto

O Loom precisa de um banco relacional para ambientes implantados. O backend persiste agentes,
recursos de memória, MCP servers, agentes A2A, provedores de identidade, políticas e perfis de
tag, registros de invocação com métricas de tokens e custo, e eventos de auditoria para as
páginas de analytics. O acesso é via SQLAlchemy, e `LOOM_DATABASE_URL` seleciona a engine em
tempo de execução: `backend/app/db.py` usa por padrão um arquivo SQLite local e troca para uma
engine com pool (`pool_pre_ping`, `pool_recycle=1800`) para qualquer outra coisa.

O SQLite é adequado para a fase de desenvolvimento local, mas não para ambientes implantados: o
backend roda como um serviço ECS com auto-scaling, então várias tasks precisam de acesso
concorrente a um banco compartilhado pela rede. O `backend/iac/rds.yaml` existente já provisiona
RDS com `Engine: postgres`, então esta ADR registra e justifica uma escolha que já está
parcialmente implícita no código, em vez de introduzir uma nova.

Duas propriedades da carga de trabalho importam para a decisão:

- **O schema evolui por DDL aditivo no startup.** `init_db()` chama
  `Base.metadata.create_all()` e depois `_migrate_add_columns()`, uma lista mantida à mão com
  cerca de 150 comandos `ALTER TABLE ... ADD COLUMN`. No PostgreSQL eles são emitidos como
  `ADD COLUMN IF NOT EXISTS`, o que torna o startup idempotente quando várias tasks sobem em
  paralelo; o ramo do SQLite não tem essa proteção. O projeto não usa Alembic.
- **Parte do padrão de leitura é analítica.** O dashboard de custos agrega custos de invocação
  por agente e intervalo de tempo, e as páginas de analytics agregam logins, ações e page views
  ao longo do tempo, com drill-down por sessão. São consultas agrupadas e segmentadas por
  tempo sobre as maiores tabelas do schema.

A [ADR 0001](0001-keycloak-as-identity-provider.md) acrescenta um segundo consumidor. O Keycloak
exige seu próprio armazenamento persistente, e seu banco padrão `dev-file` (H2 embutido) é
explicitamente inadequado para produção. O Keycloak só suporta uma lista fixa de engines, então
os requisitos dele restringem esta decisão, em vez de serem atendidos depois.

## Fatores de decisão

1. **Uma engine para os dois consumidores.** Rodar uma única tecnologia de banco para a
   aplicação e para o IdP mantém conhecimento operacional, backups, monitoramento e IaC em um
   único formato, em vez de dois.
2. **A lista de engines suportadas pelo Keycloak.** O Keycloak 26.6 suporta PostgreSQL
   14.x–18.x (testado na 18), Amazon Aurora PostgreSQL 15.x–17.x, MySQL 8.0/8.4, releases LTS
   do MariaDB, SQL Server 2019/2022 e Oracle. Qualquer coisa fora dessa lista é uma
   configuração não suportada. O PostgreSQL 13 foi removido na 26.6 após chegar ao fim de vida
   em novembro de 2025.
3. **DDL aditivo idempotente.** O caminho de migração no startup depende de
   `ADD COLUMN IF NOT EXISTS` para ser seguro quando várias tasks do backend sobem ao mesmo
   tempo.
4. **Capacidade de consulta analítica** sobre as tabelas de invocação e auditoria, sem mover
   dados para um sistema separado neste estágio.
5. **Operação gerenciada na AWS**, com criptografia em repouso, backups automatizados, Multi-AZ
   e autenticação IAM disponíveis sem trabalho customizado.
6. **Custo na escala inicial.** Uma única instância pequena deve conseguir atender aos dois
   consumidores.

## Opções consideradas

### Opção 1 — PostgreSQL, instância única compartilhada entre Loom e Keycloak (escolhida)

Uma instância RDS PostgreSQL hospedando dois bancos lógicos separados: `loom` para a aplicação
e `keycloak` para o IdP.

- **A favor:** atende aos dois consumidores com uma engine e um template de IaC; já é a engine
  em `backend/iac/rds.yaml`; suporta `ADD COLUMN IF NOT EXISTS`; suporte forte a agregações e
  window functions para as consultas de analytics; dialeto maduro no SQLAlchemy via `psycopg2`;
  `JSONB` disponível no futuro para as colunas hoje armazenadas como `TEXT` serializado; uma
  única instância para backup, patch e monitoramento.
- **Contra:** raio de impacto compartilhado — uma falha ou esgotamento no nível da instância
  derruba o login e a aplicação juntos; janelas de manutenção e upgrades de versão maior precisam
  ser coordenados entre dois consumidores com cadências de release independentes.

### Opção 2 — PostgreSQL, instâncias separadas por consumidor

- **A favor:** isolamento completo dos domínios de falha e cadência de upgrade independente; a
  carga de escrita de sessões do Keycloak não pode competir com as consultas da aplicação.
- **Contra:** praticamente dobra o custo e a superfície operacional para uma plataforma em
  escala de adoção inicial, sem ganho funcional. Razoável como um passo posterior, não como
  ponto de partida.

### Opção 3 — MySQL ou MariaDB

- **A favor:** também está na lista suportada pelo Keycloak; amplamente operado; disponível no
  RDS.
- **Contra:** exigiria migrar a IaC e o tratamento de conexão já moldados para PostgreSQL sem
  ganho algum; encaixe pior para as consultas de analytics, que são pesadas em agregação; o
  caminho de DDL aditivo perderia o `ADD COLUMN IF NOT EXISTS`, que o MySQL não suporta.

### Opção 4 — Aurora PostgreSQL (provisionado ou Serverless v2)

- **A favor:** comportamento melhor de failover e elasticidade de armazenamento; suportado pelo
  Keycloak nas versões 15.x–17.x; o Serverless v2 poderia reduzir custo em ociosidade.
- **Contra:** custo base maior que uma instância provisionada pequena; o Aurora PostgreSQL 17.0+
  exige TLS por padrão, e o driver JDBC da AWS que melhora o failover para o writer não vem
  junto com o Keycloak, precisando ser instalado deliberadamente. Vale revisitar quando os
  requisitos de disponibilidade justificarem.

### Opção 5 — SQLite em todos os ambientes

- **A favor:** zero configuração; já é o padrão de desenvolvimento local.
- **Contra:** um armazenamento em arquivo não pode ser compartilhado por várias tasks ECS, e o
  Keycloak não pode usá-lo de forma alguma. Inviável para ambientes implantados.

### Opção 6 — Um banco não relacional como o DynamoDB

- **A favor:** escala gerenciada, nenhuma instância para operar.
- **Contra:** os dados são relacionais e o padrão do projeto é SQLAlchemy sobre banco
  relacional; as agregações de analytics teriam de ser reimplementadas; e o Keycloak não pode
  usá-lo, então um segundo banco ainda seria necessário.

## Decisão

**Usar PostgreSQL como banco relacional do Loom, e fazer o Keycloak compartilhar a mesma
instância através de seu próprio banco lógico.**

Concretamente:

- **Versão.** PostgreSQL 15 ou superior. O `backend/iac/rds.yaml` atual fixa
  `EngineVersion: "15"`, que está dentro da faixa 14.x–18.x suportada pelo Keycloak. Instâncias
  novas devem ser provisionadas na 17 — bem dentro da janela de suporte do Keycloak e a maior
  versão suportada pelo Aurora PostgreSQL, mantendo a Opção 4 aberta.
- **Organização.** Uma instância, dois bancos lógicos: `loom` (o default atual de `pDbName`) e
  `keycloak`. Cada um com seu próprio usuário, dono apenas do seu banco. O Keycloak gerencia
  seu schema com Liquibase no startup e não deve compartilhar schema com as tabelas da
  aplicação, para que os upgrades dele e as migrações aditivas do backend permaneçam
  independentes.
- **Conexão do Loom.** Sem mudanças: `LOOM_DATABASE_URL` com a URL
  `postgresql+psycopg2://` vinda do Secrets Manager, `pool_pre_ping` e `pool_recycle=1800`. O
  SQLite continua suportado apenas para desenvolvimento local.
- **Conexão do Keycloak.** `KC_DB=postgres` com uma URL JDBC apontando para o banco `keycloak`.
  O Keycloak conecta **direto no endpoint da instância, sem passar pelo RDS Proxy**: ele mantém
  seu próprio pool Agroal (máximo de 100 conexões por padrão), o proxy não reduz volume de
  escrita, e conexões PostgreSQL sofrem pinning com prepared statements, que o driver JDBC usa.
  O `db-pool-max-lifetime` deve ser configurado abaixo de qualquer `wait_timeout` definido no
  servidor.
- **Somente writer.** O Keycloak sempre exige a instância primária com escrita e, por isso,
  define `targetServerType=primary` no driver JDBC. Ele nunca deve apontar para uma read
  replica.
- **Dimensionamento.** A partir do Keycloak 26, o `persistent-user-sessions` vem habilitado por
  padrão, então sessões online são escritas no banco a cada login, logout e refresh de token. A
  orientação da Red Hat é reservar aproximadamente 1.400 write IOPS e 0,35–0,7 vCPU para cada
  100 requisições de login/logout/refresh por segundo. A instância deve, portanto, ser
  dimensionada por write IOPS e CPU, não apenas por armazenamento alocado.
- **Base operacional,** já presente no template e a ser mantida: armazenamento `gp3`,
  `StorageEncrypted: true`, Multi-AZ habilitado, retenção de backup de sete dias, sem acesso
  público, e acesso restrito ao security group das tasks ECS.

## Consequências

### Positivas

- Uma engine, um template de IaC, uma única estratégia de backup e monitoramento para a
  aplicação e o IdP.
- A escolha é compatível com a matriz de suporte do Keycloak, então o deployment permanece em
  uma configuração suportada.
- O caminho de migração aditiva no startup mantém o comportamento idempotente com
  `ADD COLUMN IF NOT EXISTS`, o que importa porque as tasks do backend escalam
  horizontalmente e podem subir em paralelo.
- Consultas de analytics e agregação de custos podem continuar no banco principal por ora.
- O custo permanece em uma única instância pequena durante a adoção inicial.
- Colunas `TEXT` que hoje guardam JSON serializado podem migrar para `JSONB` no futuro sem troca
  de engine.

### Negativas

- Raio de impacto compartilhado: saturação da instância, um upgrade falho ou esgotamento de
  armazenamento afetam autenticação e aplicação ao mesmo tempo. Perder o banco significa que
  ninguém consegue entrar *e* nada funciona.
- As escritas de sessão do Keycloak e as leituras analíticas da aplicação dividem o mesmo
  orçamento de IOPS e CPU, então um pico de carga em um é visível para o outro.
- Upgrades de versão maior precisam satisfazer simultaneamente a faixa suportada pelo Keycloak
  e o backend, acoplando duas cadências de upgrade independentes.
- Passam a existir dois mecanismos de gerenciamento de schema contra a mesma instância:
  Liquibase para o Keycloak e a lista mantida à mão em `_migrate_add_columns()` para o backend.
- Operar o banco do Keycloak passa a ser responsabilidade da plataforma, incluindo o caminho de
  restauração dos dados de realm.

### Neutras

- A divisão entre SQLite para desenvolvimento e PostgreSQL para ambientes implantados já
  existia, mas esta ADR torna explícita a divergência de dialeto resultante: `DATETIME` e `REAL`
  são mapeados para `TIMESTAMP` e `DOUBLE PRECISION` no PostgreSQL, e o
  `ADD COLUMN IF NOT EXISTS` só se aplica no ramo PostgreSQL. Comportamentos que dependam
  dessas diferenças não serão capturados por testes locais contra SQLite.
- Separar em instâncias distintas mais tarde é um exercício de configuração e migração, não um
  redesenho, já que os dois bancos são logicamente separados desde o início.

## Revisitar esta decisão se

- O volume de escrita de sessões do Keycloak degradar de forma mensurável a latência das
  consultas da aplicação — nesse ponto a Opção 2 (instâncias separadas) passa a ser a resposta.
- Os requisitos de disponibilidade superarem uma instância única Multi-AZ, tornando o Aurora
  PostgreSQL válido pelo custo extra e pela configuração de TLS e driver.
- O volume de analytics e auditoria superar a instância transacional e justificar um banco
  analítico separado.
- Coordenar upgrades de versão maior entre os dois consumidores se tornar fonte recorrente de
  atraso.
- O backend adotar Alembic, o que removeria o fator de DDL idempotente desta decisão.
