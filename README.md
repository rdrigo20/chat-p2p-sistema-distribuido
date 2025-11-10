Sistema de Chat Distribuído P2P (chat.py)
Este documento descreve a implementação de um sistema de mensagens instantâneas distribuído e resiliente, desenvolvido em Python, que atende aos requisitos de um projeto de Sistemas Distribuídos, focando em arquitetura Peer-to-Peer (P2P), tolerância a falhas e consistência causal.

Arquitetura e Objetivo
O código implementa uma arquitetura Peer-to-Peer pura, onde cada instância (nó) é capaz de atuar tanto como cliente quanto como servidor. Não há um servidor central permanente. O objetivo principal é manter a comunicação em tempo real e a coerência do histórico de mensagens, mesmo com a falha de qualquer nó.

Funcionalidades Chave
1. Auto-Organização e Coordenação
Entrada na Rede (JOIN): Um nó é iniciado sem conhecimento prévio da rede. Ele envia uma requisição JOIN via Multicast para o grupo de endereço 224.1.1.1:5007.

Coordenador: O nó eleito como Coordenador é o único responsável por responder ao JOIN, atribuindo um ID único ao novo nó e fornecendo a lista atual de peers.

Heartbeat: O Coordenador envia periodicamente um sinal (HEARTBEAT) a cada 2 segundos para provar que está ativo.

2. Tolerância a Falhas (Algoritmo do Bully)
Detecção de Falha: Se um nó cliente não receber o HEARTBEAT do Coordenador dentro do prazo de 5 segundos (HEARTBEAT_TIMEOUT), ele assume que o Coordenador falhou.

Eleição Automática: O nó que detecta a falha inicia o Algoritmo do Bully. Ele envia mensagens ELECTION para todos os nós com ID maior.

Proclamação: O nó com o maior ID na rede que não receber nenhuma resposta 'OK' (ou que vencer a disputa) se autoproclama o novo Coordenador e avisa a todos os outros nós com a mensagem COORDINATOR.

3. Histórico Consistente (Consistência Causal)
Timestamp Vetorial (Vector Clock): Para garantir que todas as máquinas processem as mensagens na ordem causal correta, cada nó mantém um Vector Clock.

Regra de Entrega Causal: Ao receber uma mensagem, o nó receptor verifica o Vector Clock anexado (VC_M) contra seu próprio relógio local (VC_R). Se a mensagem for considerada fora de ordem causal, ela é colocada em um buffer de mensagens pendentes até que todas as dependências causais sejam satisfeitas. O VC também é atualizado em eventos de topologia (como PEER_UPDATE).

Requisitos de Execução
Este sistema é projetado para testes de múltiplas instâncias na mesma máquina, utilizando o endereçamento de rede interno do sistema operacional de forma estável.

Ambiente: Python 3.x com bibliotecas padrão (socket, threading, json, time).

Execução: Abra um terminal separado para cada nó.

Endereçamento:

O socket de escuta principal (BIND) utiliza '0.0.0.0' para evitar erros de permissão (WinError 10049) no Windows.

O nó se identifica com o IP real (obtido via get_local_ip()) na mensagem JOIN e configura o Multicast com base nesse IP.

Portas: É obrigatório usar uma porta P2P diferente (ex: 50001, 50002, 50003) para cada nó em cada terminal, além da porta fixa de Multicast (5007).

Como Iniciar e Testar
Inicie o Primeiro Nó (Bootstrap): O primeiro nó que você iniciar falhará no JOIN por timeout (pois não há Coordenador) e se auto-elegerá como Coordenador (ID 1).

Inicie os Nós Seguidores: Os nós subsequentes enviarão o JOIN e serão registrados pelo Coordenador ativo.

Comandos: Use os seguintes comandos no terminal:

chat <mensagem>: Envia uma mensagem para todos os nós.

status: Exibe o ID do nó, o Coordenador atual e o Vector Clock local.

exit: Encerra o nó (simula uma saída graciosa).

Para testar a Tolerância a Falhas: Inicie a rede (4 nós) e, em seguida, use o comando exit no nó que é o Coordenador. Os nós restantes iniciarão automaticamente uma eleição, e o nó com o ID mais alto será promovido a novo Coordenador.
