# Al bar
level: A1
collection: primi-passi
order: 1
topics: food, everyday
introduces: presente-indicativo
speakers: Barista m, Marta f

> Barista: Buongiorno! || Good morning!
@fn greet
> Barista: Cosa prende? || What will you have?
@fn offer-service
> Marta: Un caffè, per favore. || A coffee, please.
@fn order
@accept {Un caffè|Vorrei un caffè}(, per favore).
@accept Un caffè, grazie.
> Barista: Normale o macchiato? || Regular or with a drop of milk?
@fn ask-choice
> Marta: Macchiato, grazie. || With a drop of milk, thanks.
@fn state-preference
@accept Macchiato(, grazie).
> Marta: E anche una brioche. || And a croissant too.
@fn order
@accept (E) anche una brioche(, per favore).
> Barista: Alla crema o alla marmellata? || With custard or with jam?
@fn ask-choice
> Marta: Alla marmellata. || With jam.
@fn state-preference
@accept (Alla) marmellata(, grazie).
> Marta: Quanto costa? || How much is it?
@fn ask-price
@accept {Quanto costa|Quant'è|Quanto pago}?
> Barista: Sono due euro e cinquanta. || That's two euros fifty.
@gloss Sono = it's (literally: they are)
@fn say-price
> Marta: Ecco a lei. || Here you are.
@fn give-something
@accept {Ecco a lei|Ecco|Ecco qua}.
> Barista: Grazie, buona giornata! || Thank you, have a good day!
@fn say-goodbye

?? Cosa prende Marta da bere? || What does Marta have to drink? @s3,s5
- Un tè || A tea
* Un caffè macchiato || A coffee with a drop of milk
- Un cappuccino || A cappuccino
?? Che brioche sceglie? || Which croissant does she choose? @s8
- Alla crema || With custard
* Alla marmellata || With jam
- Al cioccolato || With chocolate
?? Marta paga con la carta? || Does Marta pay by card? @s11 = notStated
