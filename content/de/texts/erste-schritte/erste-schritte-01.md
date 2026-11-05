# Die neue Wohnung
level: A1
collection: erste-schritte
order: 1
status: draft
topics: home
introduces: artikel
register: du
speakers: Jonas m, Lena f

Lena ist neu in Leipzig. || Lena is new in Leipzig.
Die Wohnung ist klein, aber hell. || The flat is small but bright.
Das Zimmer hat ein Fenster. || The room has a window.
Der Tisch steht am Fenster. || The table is by the window.
Die Lampe ist neu. || The lamp is new.
Das Bett ist alt, aber gut. || The bed is old but good.

> Jonas: Hallo, Lena! || Hi, Lena!
@fn greet
> Jonas: Ist das die Wohnung? || Is this the flat?
@fn ask-where
> Lena: Ja, das ist die Wohnung. || Yes, this is the flat.
@fn confirm
> Lena: Hier ist die Küche. || Here is the kitchen.
@fn say-where
> Jonas: Und wo ist das Bad? || And where is the bathroom?
@fn ask-where
@accept (Und) wo ist das {Bad|Badezimmer}?
> Lena: Das Bad ist dort. || The bathroom is over there.
@fn say-where
> Jonas: Die Wohnung ist wirklich schön. || The flat is really nice.
@fn praise
@accept Die Wohnung ist {wirklich|sehr} schön.

?? Wo wohnt Lena? || Where does Lena live? @s1
- In Berlin || In Berlin
* In Leipzig || In Leipzig
- In Hamburg || In Hamburg
?? Ist die Wohnung groß? || Is the flat big? @s2 = no
?? Ist das Bett neu? || Is the bed new? @s6 = no
?? Hat die Wohnung einen Balkon? || Does the flat have a balcony? @s2,s3 = notStated
