# Requisitos de correção — v1.0-alpha.5

## Objetivo

Fechar os defeitos observados ao aplicar a alpha.4 aos relatórios reais do
semestre, sem alterar relatórios de entrada, versões anteriores ou gates de
conteúdo e áudio.

## Requisitos obrigatórios

1. Uma consulta em idioma diferente da fonte não pode reutilizar obra,
   enunciado, capítulo, seção ou rótulo de exercício como se fossem tradução.
2. Sem `localized_terms` conferidos, a automação só pode usar notação ou a
   combinação de autor/canal oficial com código numérico transportável.
3. Consultas sem âncora suficiente permanecem `LOCALIZATION_REQUIRED` e não são
   enviadas ao provedor automático.
4. Busca manual e automática processam somente `REQUIRED` por padrão.
5. `OPTIONAL` e `CONTROL_NO_AUTOMATIC` exigem `--unit-id`,
   `--include-optional` ou `--include-control`; controle nunca entra por
   omissão.
6. O relatório de busca separa progresso obrigatório das três políticas.
7. A ausência de `yt-dlp` oferece comando de instalação e fallback manual sem
   API key. Um preflight offline mostra ferramentas e capacidades sem instalar
   nada.
8. Título, descrição, resultado de busca, legenda e inventário de faixa
   continuam incapazes de aprovar vídeo ou dublagem.
9. O curso real dos relatórios preserva 18 erros obrigatórios, três rotas
   difíceis opcionais e um controle fácil, todos com estado explícito.
10. Sem áudio PT/EN realmente ouvido e registrado, nenhuma rota pode ser
    liberada e o tempo útil permanece zero.

## Aceitação

- regressões de localização, política de rota, prompt manual e preflight;
- suíte completa, lint, tipagem, demo e validação de workspace;
- reaplicação ao mapa real dos relatórios do semestre;
- instalação limpa do núcleo e do extra `automation` sem credencial;
- baseline direta da alpha.4, manifesto atual, ZIP de raiz única e hashes;
- `promotion_ready=false` e limitações pedagógicas explícitas.
