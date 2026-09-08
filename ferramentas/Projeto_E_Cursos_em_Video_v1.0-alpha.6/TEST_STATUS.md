# Estado dos testes — v1.0-alpha.6 — 2026-08-29

## Resultado do fechamento

- `135` testes `unittest` aprovados no Python `3.13.9`;
- `ruff 0.12.0 check --no-cache projeto_e_video tests`: aprovado;
- `mypy 1.17.1 projeto_e_video tests --ignore-missing-imports
  --no-incremental`: aprovado em 33 arquivos;
- demonstração offline e validação do workspace PDF-only: aprovadas;
- instalação limpa do núcleo e do extra `automation`, console e `pip check`:
  aprovadas;
- baseline direta, manifesto, segredo, estrutura, raiz única, CRC e hashes do
  ZIP: aprovados;
- nenhuma fonte, imagem, mídia, cache, metadata de build ou credencial entrou
  na release.

## Regressões novas da alpha.6

- um PDF explícito é uma fonte autônoma, mesmo que exista `manifest.json` e
  pasta de imagens ao lado;
- somente pasta FlashList ou `manifest.json` explícito ativa o pacote
  estruturado de itens;
- remover imagem vizinha depois da ingestão PDF-only não invalida a fonte;
- pacote FlashList explícito preserva uma unidade por item e a dificuldade
  controla `REQUIRED`, `OPTIONAL` ou `CONTROL_NO_AUTOMATIC`;
- `EXACT_OBJECT_MINIMAL` executa antes das consultas mais qualificadas e não
  mistura autor, número nem ação genérica no objeto mínimo;
- fallback sem termo localizado continua produzindo consulta normal, nunca
  string vazia;
- ID direto do YouTube exige exatamente 11 caracteres válidos; placeholder é
  rejeitado;
- a mesma janela e os mesmos hashes não podem provar unidades distintas;
- observação somente visual pode ser registrada como `UNVERIFIABLE` sem fala
  inventada, mas nunca é elegível.

## Piloto real PDF-only

- entrada explícita: somente `relatorio_semanal.pdf`, SHA-256
  `e15c4543…f0db4`;
- uma fonte `FILE`, novamente verificada sem depender de arquivos vizinhos;
- mapa `V1_VERIFIED`: 16 unidades de resolução, 14 obrigatórias e dois
  controles fáceis;
- primeira passagem: 126 consultas exatas PT/EN/ES, zero candidato;
- busca curta corrigida e expansões: 174 tentativas, 77 candidatos de
  metadados e ao menos um candidato nas 14 obrigatórias;
- amostra interna de sete candidatos: 11 `NAO_VERIFICAVEL`, 2 `PARCIAL` e 3
  `TEORIA_APENAS` no conjunto de 16 unidades;
- zero `EXATO`, zero `EQUIVALENTE_RIGOROSO`, zero rota, zero segundo útil;
- curso `PARCIAL`, `promotion_ready=false`, workspace `valid=true`.

Os 77 candidatos provam melhora de recall, não cobertura. O teste não ouviu
faixa PT/EN e não converteu título, URL válida, frame ou teoria em curso.

## Baselines

```text
alpha.5 direta
sha256: b4aa7e94e93ede8ea69a205f7f52b0401474dc71c157184b6214feb7507940ba
arquivos: 77
bytes: 620100

Projeto E v4.7 semântico
sha256: abf5eb9173772e4215cd10b45d587c29d00c90b497be8820101ed2466bb0c755
arquivos: 331
bytes: 5989874
```

## O que os testes não provam

Eles não demonstram resolução adequada para todas as unidades, compreensão da
dublagem, qualidade docente, retenção, acessibilidade universal ou eficácia
com alunos. `promotion_ready=false` permanece obrigatório.
