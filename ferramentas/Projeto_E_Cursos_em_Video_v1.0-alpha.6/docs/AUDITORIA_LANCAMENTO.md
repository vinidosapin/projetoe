# Auditoria de lançamento — v1.0-alpha.6

## Parecer

**Apta como alpha técnica distribuível, com `promotion_ready=false`.**

“Apta” significa que contratos, bloqueios, ingestão PDF-only, busca,
instalação e integridade da distribuição foram verificados. Não significa curso
completo, eficácia pedagógica ou substituição de professor.

## Matriz de aceitação

| Gate | Evidência | Estado |
|---|---|---|
| versão isolada | pasta alpha.6 e baseline direta da alpha.5 | aprovado |
| origem preservada | 77 arquivos, 620.100 bytes, hash `b4aa7e…940ba` | aprovado |
| escopo PDF | PDF explícito vira uma fonte; vizinhos não são inferidos | aprovado |
| pacote explícito | pasta/manifesto FlashList preserva um item por unidade | aprovado |
| busca | objeto mínimo primeiro; tentativas qualificadas separadas | aprovado |
| link direto | placeholder e ID inválido são rejeitados | aprovado |
| evidência específica | janela + hashes não podem ser reciclados | aprovado |
| mapa antes da busca | V0 sem consultas; V1 obrigatório | aprovado |
| metadados | título, URL, busca e inventário não aprovam conteúdo/áudio | aprovado |
| conteúdo interno | timestamps + fala/transcrição + visual + passos | aprovado |
| faixa PT/EN | escuta continua gate independente | aprovado |
| curso real | 1 PDF, 16 unidades, lacunas preservadas | aprovado |
| integridade | curso rederivado; workspace `valid=true` | aprovado |
| suíte | 135 testes, Ruff e mypy | aprovado |
| instalação | núcleo e extra em venv limpo, console e `pip check` | aprovado |
| release | baseline, manifesto, ZIP, CRC, hashes e reprodução | aprovado |
| eficácia pedagógica | rotas completas, especialistas e alunos | pendente |

## Teste real que motivou a versão

As saídas antigas continham sete IDs de YouTube inventados e declaravam 35
unidades cobertas ao reciclar somente quatro vídeos genéricos. O terceiro
relatório também revelou que 126 consultas exatas extensas em PT/EN/ES podiam
retornar zero candidato.

A passagem mínima corrigida e as expansões registraram 174 tentativas e 77
candidatos, alcançando as 14 unidades obrigatórias por metadados. Isso resolveu
o recall da descoberta, não a cobertura pedagógica. Na amostra interna, nenhum
candidato passou simultaneamente por resolução completa e áudio PT/EN ouvido;
o resultado foi zero rota e zero tempo útil.

A execução final recebeu apenas `relatorio_semanal.pdf`. O manifesto contém uma
única fonte `FILE`, e a validação continuou válida independentemente das imagens
vizinhas usadas em outro fluxo.

## Limitações residuais

- busca finita nunca prova exaustão da internet ou de todos os idiomas;
- vídeo adequado pode não existir, sair do ar, exigir conta ou estar bloqueado;
- tradução, transcrição, quadros e correspondência matemática exigem revisão;
- agente sem capacidade de ouvir não pode preencher `audio_reviews`;
- qualidade docente, retenção e aceleração precisam de avaliação com alunos.

Essas limitações produzem lacuna ou curso `PARCIAL`, nunca preenchimento
automático com vídeo inadequado.

## Decisão

O ZIP pode ser usado para operar e avaliar tecnicamente a alpha.6. Nenhum dos
links do piloto deve ser entregue como curso; a promoção pedagógica permanece
proibida.
