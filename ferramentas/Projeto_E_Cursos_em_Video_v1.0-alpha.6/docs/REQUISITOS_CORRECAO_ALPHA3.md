# Requisitos verificáveis da alpha.3

Este documento congela o escopo técnico derivado do piloto real de 25/08/2026.
"Funcional" significa que o programa executa o fluxo, preserva o progresso e
produz estados verdadeiros. Não significa que a internet contenha um vídeo
adequado para todo objeto nem que assistir a um vídeo prove aprendizagem.

## Critérios obrigatórios

1. A `alpha.2` permanece imutável e sua árvore é identificada pela baseline.
2. Uma entrada literal longa não pode falhar ao ser sondada como caminho.
3. Uma criação pode reunir fontes não contíguas; todas entram no manifesto e no
   hash do curso sem serem copiadas para a pasta versionada.
4. Toda localização de unidade deve estar vinculada a um de seus `source_ids`;
   referências externas não inventariadas são rejeitadas.
5. O mapa V0 materializa exatamente zero consultas. Só o V1 verificado registra
   identidade bibliográfica e impressões digitais de busca: idioma da fonte,
   autor/obra, edição, capítulo/seção/exercício, frases exatas, fórmulas, termos
   e ecossistemas oficiais, quando conhecidos.
6. Consultas em outro idioma não reutilizam cegamente um título português.
   Teoria começa por uma descoberta curta no ecossistema da fonte; exercícios
   começam pelo objeto/número exato, ganham uma descoberta ampla separada e só
   depois equivalente estrutural. Teoria genérica nunca encerra resolução.
7. Nenhuma consulta tenta reunir todos os metadados em uma frase gigante. Canal
   ou curso oficial, número do exercício, frase distintiva, fórmula e tradução
   são passagens separadas, removendo uma restrição por vez e registrando cada
   tentativa.
8. A busca automática é incremental: não repete consultas concluídas, não apaga
   candidatos anteriores, pode retentar falhas explicitamente e informa
   pendências por unidade e idioma. Importações rederivam o relatório; contagens
   `Q-...` e `OPEN_EXPANSION` permanecem separadas e coerentes.
9. A triagem por metadados reduz ruído e explica sua pontuação, mas nunca aprova
   conteúdo. Colisão lexical como `E(X!)` versus momento fatorial deve receber
   risco explícito.
10. Tags internas de provedores não derrubam o inventário inteiro. O valor bruto
   é preservado, a parte BCP-47 confiável é normalizada e uma advertência fica
   visível.
11. A coleta solicita apenas artefatos pedidos, escolhe legendas explicitamente
    e usa seções curtas para frames/áudio. Para frame, prefere stream HTTPS
    progressivo antes de HLS; falhas de legenda, frame e áudio são independentes.
12. A revisão de áudio permanece humana ou feita por agente que realmente possa
    ouvir. O sistema prepara um pacote compacto de revisão e nunca converte
    legenda, metadado ou ASR isolado em dublagem aprovada.
13. Vários vídeos podem formar uma rota composta somente quando a união das
    evidências internas cobre todos os passos, cada componente é localmente
    exato/equivalente, não há conflito/pré-requisito ausente e uma faixa PT/EN
    foi ouvida para todos os passos daquele componente.
14. O curso mostra rótulos humanos para falhas, não códigos internos; o HTML não
    duplica segmentos e o tempo útil soma somente intervalos liberados.
15. Validação reconstrói manifesto, vínculo de fontes, consultas, candidatos,
    inventário, evidências, auditoria, rota composta, Markdown e HTML.
16. Prompts gerados permanecem índices compactos, não cópias integrais de
    ledgers; entradas grandes não podem criar prompts sem limite prático.
17. Testes cobrem matemática, programação, português, vídeo sem transcrição,
    título enganoso, erro matemático, equivalência, pré-requisito ausente,
    composição, exercício opcional, controle fácil, retomada e falhas parciais.
18. Um piloto independente usa fonte bibliográfica e exercícios reais, registra
    buscas com e sem resultado e não transforma ausência de vídeo em aprovação.
19. O pacote final passa testes unitários, instalação limpa, demonstração,
    validação de release e ZIP de raiz única, sem mídia, caches ou segredos.

## Condição de não promoção

`promotion_ready` permanece `false`. Uma validação pedagógica externa com
alunos/professores é requisito separado; fixture e piloto técnico não medem
retenção nem qualidade docente.
