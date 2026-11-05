# Wer bist du?
level: A1
collection: erste-schritte
order: 3
status: draft
topics: people
introduces: sein-haben
register: du
speakers: Tom m, Lena f

> Tom: Hallo, ich bin Tom. || Hi, I'm Tom.
@fn introduce
> Tom: Bist du auch neu hier? || Are you new here too?
> Lena: Ja, ich bin Lena. || Yes, I'm Lena.
@fn introduce
@accept Ja, ich {bin|heiße} Lena.
> Lena: Woher kommst du? || Where are you from?
@fn ask-origin
@accept Woher kommst du (denn)?
> Tom: Ich komme aus Bremen. || I'm from Bremen.
@fn say-origin
> Tom: Hast du Geschwister? || Do you have any brothers or sisters?
@fn ask-about
> Lena: Ja, ich habe einen Bruder. || Yes, I have a brother.
@fn tell-about
> Lena: Er ist zwölf Jahre alt. || He's twelve years old.
> Tom: Ich habe keine Geschwister, aber ich habe einen Hund. || I don't have any brothers or sisters, but I have a dog.
> Lena: Wie heißt der Hund? || What's the dog called?
@fn ask-about
@accept Wie heißt {der|dein} Hund?
> Tom: Er heißt Bruno. || He's called Bruno.
> Tom: Er ist alt und sehr müde. || He's old and very tired.

?? Woher kommt Tom? || Where is Tom from? @s5
* Aus Bremen || From Bremen
- Aus Leipzig || From Leipzig
- Aus Berlin || From Berlin
?? Hat Lena einen Bruder? || Does Lena have a brother? @s7 = yes
?? Wie heißt Toms Hund? || What is Tom's dog called? @s11
* Bruno || Bruno
- Tom || Tom
- Max || Max
