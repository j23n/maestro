# Messaggi tra amiche
level: A2
collection: vita-quotidiana
order: 2
topics: friends, plans
introduces: futuro-semplice
speakers: Chiara f, Sara f

> Chiara: Ciao Sara, sei libera venerdì sera? || Hi Sara, are you free on Friday evening?
@fn ask-plans
@accept Ciao Sara, sei libera {venerdì|venerdì sera}?
> Sara: Credo di sì, perché? || I think so, why?
@fn say-unsure
@accept {Credo di sì|Penso di sì|Forse}(, perché)?
> Chiara: C'è un concerto jazz al parco, vieni con me? || There's a jazz concert in the park, will you come with me?
@fn invite
> Sara: Volentieri! A che ora comincia? || Gladly! What time does it start?
@fn accept
@accept {Volentieri|Con piacere|Certo}! A che ora {comincia|inizia}?
> Chiara: Alle nove, ma ci vediamo prima per mangiare una pizza. || At nine, but let's meet before to have a pizza.
@fn suggest
> Sara: Perfetto, porterò anche mio fratello, se va bene. || Perfect, I'll bring my brother too, if that's OK.
@fn ask-permission
> Chiara: Certo! Prenoterò un tavolo per tre alle sette e mezza. || Of course! I'll book a table for three at half past seven.
@fn agree
> Sara: Se piove, cosa facciamo? || If it rains, what do we do?
@fn ask-what-if
@accept {Se piove|E se piove}, {cosa|che cosa|che} facciamo?
> Chiara: Il concerto si farà comunque, sotto un tendone. || The concert will go ahead anyway, under a marquee.
@fn reassure
> Sara: Allora a venerdì! || See you on Friday, then!
@fn confirm
@accept {Allora a venerdì|A venerdì|Ci vediamo venerdì}!

?? Dove si terrà il concerto? || Where will the concert be? @s3
- In un teatro || In a theatre
* Al parco || In the park
- In pizzeria || At the pizzeria
?? Per quante persone prenota Chiara? || How many people does Chiara book for? @s7
- Per due || For two
* Per tre || For three
- Per quattro || For four
?? Se piove, il concerto è annullato? || If it rains, is the concert cancelled? @s9 = no
