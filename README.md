# Projeto E — Convergência Acadêmica 0.208-alpha.1

Release de reorganização da experiência do aluno. O conteúdo acadêmico e o conjunto de URLs permanecem **idênticos à v0.207-alpha.1**; esta rodada altera somente a interface, a navegação e a acessibilidade do entrypoint.

## Conteúdo preservado

- Tópicos canônicos: **1571**
- Tópicos cobertos: **1263 (80,39%)**
- Lacunas: **308**
- Associações tópico→vídeo: **2052**
- Registros ativos: **1892**
- URLs únicas: **739**
- Novas associações nesta rodada: **0**
- Novos tópicos cobertos: **0**
- URLs novas nesta rodada: **0**

## Interface v0.208

A navegação foi convertida para um fluxo mestre-detalhe: disciplina → área → módulo → tópico selecionado. O aluno vê apenas um módulo por vez e apenas as videoaulas do tópico escolhido, reduzindo densidade visual. Busca global, filtros simples, navegação anterior/próximo, foco visível, atalho para conteúdo e menu responsivo foram mantidos no próprio HTML, sem dependências externas.

O corpus de dados continua sendo a baseline v0.207; por isso os artefatos de auditoria em `dados/` mantêm seus nomes v0.207.
