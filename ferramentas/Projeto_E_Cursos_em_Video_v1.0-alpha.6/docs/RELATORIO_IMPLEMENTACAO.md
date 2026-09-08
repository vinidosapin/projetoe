# Relatório de implementação — v1.0-alpha.6

## Resultado

A alpha.6 é uma sucessora isolada da alpha.5. Ela corrige os defeitos que
produziam links inexistentes, falsa cobertura por reciclagem de vídeos e recall
zero em consultas excessivamente qualificadas. Também fixa a fronteira da
entrada: cobrir um relatório PDF significa usar somente esse arquivo.

Os gates pedagógicos e audiovisuais não foram reduzidos. A versão está
funcional como alpha técnica, mas `promotion_ready=false`: ainda não há curso
de vídeos liberado para os erros do semestre.

## Correções

### Relatório é arquivo, não fila de imagens

- `relatorio_semanal.pdf` explícito gera uma única fonte `FILE`;
- nenhum `manifest.json` ou diretório de imagens vizinho é inferido;
- alterar ou remover essas imagens não invalida o workspace PDF-only;
- pasta FlashList ou seu `manifest.json`, quando fornecidos explicitamente,
  continuam disponíveis como outro modo de entrada e preservam um item por
  unidade.

### Busca com recall mensurável

- `EXACT_OBJECT_MINIMAL` consulta primeiro somente o objeto distintivo
  localizado;
- autor, obra, número e ação genérica permanecem em tentativas separadas;
- a busca estrita, o ecossistema da fonte e o equivalente rigoroso continuam
  registrados;
- candidatos continuam sendo metadados, independentemente da pontuação.

### Links e evidências

- IDs diretos do YouTube precisam ter a forma real de 11 caracteres;
- termos de busca e placeholders não viram links;
- o link é reaberto antes da entrega;
- intervalos e hashes idênticos não podem ser reciclados para afirmar que um
  mesmo vídeo cobre exercícios distintos;
- inspeção visual sem fala/transcrição só pode resultar em estado não
  verificável.

## Execução real

O teste canônico está fora da release em:

`assistente_virtual/semestre/pilotos_projeto_e/2026-08-28_relatorios_semanais_slides_alpha5/07_relatorio_24_30_alpha6_pdf_only/workspace/`

Ele usou exclusivamente o PDF semanal de 24–30/08. O mapa V1 contém 16
unidades, sendo 14 erros obrigatórios e dois controles. A busca mínima corrigida
e expansões encontraram 77 candidatos de metadados para as 14 obrigatórias,
contra zero em 126 buscas exatas anteriores.

Sete candidatos foram submetidos à amostra de auditoria. O resultado agregado
foi 11 unidades `NAO_VERIFICAVEL`, duas `PARCIAL` e três `TEORIA_APENAS`.
Nenhum conteúdo ficou `EXATO` ou `EQUIVALENTE_RIGOROSO`; nenhuma faixa PT/EN
foi ouvida; nenhuma rota foi liberada. O workspace é estruturalmente válido e
o curso permanece `PARCIAL`, com zero segundo recomendado.

## Organização preservada

```text
projeto_e_video/   motor determinístico e CLI
PROMPTS/           papéis permanentes desta versão
schemas/           contratos JSON
examples/          moldes não promovíveis
tests/             regressões offline e sem API key
docs/              operação, auditoria e governança
<workspace>/       fontes, ledgers, evidências e curso; sempre externo
```

## Limite da declaração

A alpha está pronta para operação e avaliação técnica. Ela não garante que
exista vídeo adequado para qualquer exercício e este runtime não pode ouvir
áudio. Cada erro ainda exige inspeção interna passo a passo e escuta da faixa
PT/EN antes de uma rota estudantil ser liberada.

Consulte `REQUISITOS_CORRECAO_ALPHA6.md`, `AUDITORIA_LANCAMENTO.md` e o
relatório externo `RELATORIO_TESTE_ALPHA6.md`.
