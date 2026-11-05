# Im Café
level: A1
collection: erste-schritte
order: 2
status: draft
topics: food
introduces: praesens
register: Sie
speakers: Kellnerin f, Lena f, Jonas m

Lena und Jonas sitzen im Café. || Lena and Jonas are sitting in a café.
Sie trinken gern Kaffee. || They like drinking coffee.
Lena studiert Musik. || Lena studies music.
Jonas arbeitet hier in Leipzig. || Jonas works here in Leipzig.

> Kellnerin: Guten Tag! || Hello!
@fn greet
> Kellnerin: Was trinken Sie? || What would you like to drink?
@fn offer-service
> Lena: Ich nehme einen Kaffee, bitte. || I'll have a coffee, please.
@fn order
@accept {Ich nehme|Ich möchte|Ich hätte gern} einen Kaffee(, bitte).
@accept Einen Kaffee(, bitte).
> Jonas: Ich trinke einen Tee. || I'll have a tea.
@fn order
> Kellnerin: Und was essen Sie? || And what would you like to eat?
@fn offer-service
> Jonas: Ich esse ein Stück Kuchen. || I'll have a piece of cake.
> Lena: Ich esse nichts, danke. || Nothing to eat for me, thanks.
@fn decline
@accept {Ich esse nichts|Nichts}, danke.

Der Kaffee kommt schnell. || The coffee comes quickly.
Lena spielt heute Abend Klavier. || Lena is playing the piano this evening.

?? Was studiert Lena? || What does Lena study? @s3
* Musik || Music
- Medizin || Medicine
- Deutsch || German
?? Was trinkt Jonas? || What does Jonas drink? @s8
- Kaffee || Coffee
* Tee || Tea
- Wasser || Water
?? Isst Lena Kuchen? || Does Lena eat cake? @s11 = no
