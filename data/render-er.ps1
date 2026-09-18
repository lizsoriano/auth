Add-Type -AssemblyName System.Drawing

$width = 3200
$height = 2200
$bitmap = [System.Drawing.Bitmap]::new($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$graphics.Clear([System.Drawing.Color]::FromArgb(248, 250, 252))

$titleFont = [System.Drawing.Font]::new('Segoe UI', 32, [System.Drawing.FontStyle]::Bold)
$subtitleFont = [System.Drawing.Font]::new('Segoe UI', 15)
$tableFont = [System.Drawing.Font]::new('Segoe UI', 20, [System.Drawing.FontStyle]::Bold)
$fieldFont = [System.Drawing.Font]::new('Consolas', 13)
$fieldBoldFont = [System.Drawing.Font]::new('Consolas', 13, [System.Drawing.FontStyle]::Bold)
$relationFont = [System.Drawing.Font]::new('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
$legendFont = [System.Drawing.Font]::new('Segoe UI', 14)

$textBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(15, 23, 42))
$mutedBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(71, 85, 105))
$headerBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(30, 64, 175))
$headerTextBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
$tableBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
$pkBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(180, 83, 9))
$fkBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(4, 120, 87))
$borderPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(100, 116, 139), 2)
$relationPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(51, 65, 85), 3)

$graphics.DrawString('Diagrama entidad-relacion - Biblioteca', $titleFont, $textBrush, 70, 35)
$graphics.DrawString('Fuente: db/schema.sql  |  PostgreSQL', $subtitleFont, $mutedBrush, 75, 88)

$tables = @{
    formats = @{ X=80; Y=210; W=570; Fields=@(
        'PK  format_id : bigint', '    name : varchar(80) NOT NULL', '    description : text NULL') }
    categories = @{ X=80; Y=540; W=570; Fields=@(
        'PK  category_id : bigint', '    name : varchar(120) NOT NULL', '    description : text NULL') }
    authors = @{ X=80; Y=1060; W=570; Fields=@(
        'PK  author_id : bigint', '    first_name : varchar(120) NOT NULL', '    last_name : varchar(120) NULL', '    biography : text NULL', '    created_at : timestamptz NOT NULL', '    updated_at : timestamptz NOT NULL') }
    genres = @{ X=80; Y=1650; W=570; Fields=@(
        'PK  genre_id : bigint', '    name : varchar(120) NOT NULL', '    description : text NULL') }
    books = @{ X=1030; Y=430; W=720; Fields=@(
        'PK  book_id : bigint', '    isbn : varchar(17) NOT NULL UNIQUE', '    title : varchar(300) NOT NULL', '    publication_year : smallint NOT NULL', '    price : numeric(12,2) NOT NULL', '    stock : integer NOT NULL', 'FK  format_id : bigint NOT NULL', 'FK  category_id : bigint NOT NULL', '    created_at : timestamptz NOT NULL', '    updated_at : timestamptz NOT NULL') }
    book_authors = @{ X=840; Y=1110; W=720; Fields=@(
        'PK, FK  book_id : bigint', 'PK, FK  author_id : bigint', '        author_order : smallint NOT NULL') }
    book_genres = @{ X=840; Y=1640; W=720; Fields=@(
        'PK, FK  book_id : bigint', 'PK, FK  genre_id : bigint') }
    book_images = @{ X=2050; Y=290; W=780; Fields=@(
        'PK  image_id : bigint', 'FK  book_id : bigint NOT NULL', '    image_url : text NOT NULL', '    alt_text : varchar(300) NULL', '    display_order : smallint NOT NULL', '    is_cover : boolean NOT NULL', '    created_at : timestamptz NOT NULL') }
    concepts = @{ X=2450; Y=1660; W=650; Fields=@(
        'PK  concept_id : bigint', '    name : varchar(200) NOT NULL') }
    book_concepts = @{ X=1790; Y=1230; W=790; Fields=@(
        'PK, FK  book_id : bigint', 'PK, FK  concept_id : bigint', '        definition : text NOT NULL', '        created_at : timestamptz NOT NULL', '        updated_at : timestamptz NOT NULL') }
    users = @{ X=2380; Y=40; W=720; Fields=@(
        'PK  user_id : bigint', '    email : varchar(254) NOT NULL UNIQUE', '    password_hash : text NOT NULL', '    display_name : varchar(150) NOT NULL', '    is_admin : boolean NOT NULL', '    is_active : boolean NOT NULL', '    created_at : timestamptz NOT NULL', '    updated_at : timestamptz NOT NULL') }
}

function Get-TableHeight($table) { return 70 + ($table.Fields.Count * 31) + 18 }

function Draw-Relation($parentName, $childName, $parentSide, $childSide, $bend = $null) {
    $p = $tables[$parentName]
    $c = $tables[$childName]
    $ph = Get-TableHeight $p
    $ch = Get-TableHeight $c
    $start = switch ($parentSide) {
        'right'  { [System.Drawing.PointF]::new($p.X + $p.W, $p.Y + $ph / 2) }
        'left'   { [System.Drawing.PointF]::new($p.X, $p.Y + $ph / 2) }
        'top'    { [System.Drawing.PointF]::new($p.X + $p.W / 2, $p.Y) }
        'bottom' { [System.Drawing.PointF]::new($p.X + $p.W / 2, $p.Y + $ph) }
    }
    $end = switch ($childSide) {
        'right'  { [System.Drawing.PointF]::new($c.X + $c.W, $c.Y + $ch / 2) }
        'left'   { [System.Drawing.PointF]::new($c.X, $c.Y + $ch / 2) }
        'top'    { [System.Drawing.PointF]::new($c.X + $c.W / 2, $c.Y) }
        'bottom' { [System.Drawing.PointF]::new($c.X + $c.W / 2, $c.Y + $ch) }
    }
    if ($null -eq $bend) {
        $graphics.DrawLine($relationPen, $start, $end)
    } else {
        $mid1 = [System.Drawing.PointF]::new($bend[0], $start.Y)
        $mid2 = [System.Drawing.PointF]::new($bend[0], $end.Y)
        $graphics.DrawLines($relationPen, [System.Drawing.PointF[]]@($start, $mid1, $mid2, $end))
    }
    $graphics.FillEllipse([System.Drawing.Brushes]::White, $start.X - 19, $start.Y - 17, 38, 34)
    $graphics.DrawString('1', $relationFont, $textBrush, $start.X - 7, $start.Y - 14)
    $graphics.FillRectangle([System.Drawing.Brushes]::White, $end.X - 29, $end.Y - 17, 58, 34)
    $graphics.DrawString('0..N', $relationFont, $textBrush, $end.X - 24, $end.Y - 14)
}

function Draw-Cardinality($parentName, $childName, $parentSide, $childSide) {
    $p = $tables[$parentName]
    $c = $tables[$childName]
    $ph = Get-TableHeight $p
    $ch = Get-TableHeight $c
    $start = switch ($parentSide) {
        'right'  { [System.Drawing.PointF]::new($p.X + $p.W, $p.Y + $ph / 2) }
        'left'   { [System.Drawing.PointF]::new($p.X, $p.Y + $ph / 2) }
        'top'    { [System.Drawing.PointF]::new($p.X + $p.W / 2, $p.Y) }
        'bottom' { [System.Drawing.PointF]::new($p.X + $p.W / 2, $p.Y + $ph) }
    }
    $end = switch ($childSide) {
        'right'  { [System.Drawing.PointF]::new($c.X + $c.W, $c.Y + $ch / 2) }
        'left'   { [System.Drawing.PointF]::new($c.X, $c.Y + $ch / 2) }
        'top'    { [System.Drawing.PointF]::new($c.X + $c.W / 2, $c.Y) }
        'bottom' { [System.Drawing.PointF]::new($c.X + $c.W / 2, $c.Y + $ch) }
    }
    $graphics.FillEllipse([System.Drawing.Brushes]::White, $start.X - 19, $start.Y - 17, 38, 34)
    $graphics.DrawString('1', $relationFont, $textBrush, $start.X - 7, $start.Y - 14)
    $graphics.FillRectangle([System.Drawing.Brushes]::White, $end.X - 29, $end.Y - 17, 58, 34)
    $graphics.DrawString('0..N', $relationFont, $textBrush, $end.X - 24, $end.Y - 14)
}

# Relaciones: la tabla padre está del lado 1; la tabla que contiene la FK, del lado 0..N.
Draw-Relation 'formats' 'books' 'right' 'left'
Draw-Relation 'categories' 'books' 'right' 'left'
Draw-Relation 'books' 'book_authors' 'bottom' 'top'
Draw-Relation 'authors' 'book_authors' 'right' 'left'
Draw-Relation 'books' 'book_genres' 'bottom' 'top' @(780)
Draw-Relation 'genres' 'book_genres' 'right' 'left'
Draw-Relation 'books' 'book_images' 'right' 'left'
Draw-Relation 'books' 'book_concepts' 'right' 'left' @(1770)
Draw-Relation 'concepts' 'book_concepts' 'left' 'right'

foreach ($entry in $tables.GetEnumerator()) {
    $name = $entry.Key
    $t = $entry.Value
    $h = Get-TableHeight $t
    $graphics.FillRectangle($tableBrush, $t.X, $t.Y, $t.W, $h)
    $graphics.DrawRectangle($borderPen, $t.X, $t.Y, $t.W, $h)
    $graphics.FillRectangle($headerBrush, $t.X, $t.Y, $t.W, 58)
    $graphics.DrawString($name, $tableFont, $headerTextBrush, $t.X + 18, $t.Y + 12)
    $rowY = $t.Y + 70
    foreach ($field in $t.Fields) {
        $brush = $textBrush
        $font = $fieldFont
        if ($field -match '^PK') { $brush = $pkBrush; $font = $fieldBoldFont }
        elseif ($field -match '^FK') { $brush = $fkBrush; $font = $fieldBoldFont }
        $graphics.DrawString($field, $font, $brush, $t.X + 16, $rowY)
        $rowY += 31
    }
}

# Las etiquetas se vuelven a dibujar sobre las tablas para que permanezcan legibles.
Draw-Cardinality 'formats' 'books' 'right' 'left'
Draw-Cardinality 'categories' 'books' 'right' 'left'
Draw-Cardinality 'books' 'book_authors' 'bottom' 'top'
Draw-Cardinality 'authors' 'book_authors' 'right' 'left'
Draw-Cardinality 'books' 'book_genres' 'bottom' 'top'
Draw-Cardinality 'genres' 'book_genres' 'right' 'left'
Draw-Cardinality 'books' 'book_images' 'right' 'left'
Draw-Cardinality 'books' 'book_concepts' 'right' 'left'
Draw-Cardinality 'concepts' 'book_concepts' 'left' 'right'

$legendY = 2070
$graphics.DrawString('Leyenda:', $relationFont, $textBrush, 80, $legendY)
$graphics.DrawString('PK = clave primaria', $legendFont, $pkBrush, 185, $legendY)
$graphics.DrawString('FK = clave foranea', $legendFont, $fkBrush, 440, $legendY)
$graphics.DrawString('1 - 0..N = un registro padre puede relacionarse con cero o muchos hijos; cada hijo referencia exactamente un padre.', $legendFont, $textBrush, 690, $legendY)
$graphics.DrawString('users no tiene claves foraneas en el esquema.', $legendFont, $mutedBrush, 80, $legendY + 42)

$outputPath = Join-Path $PSScriptRoot 'diagrama-er.png'
$bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)

$graphics.Dispose()
$bitmap.Dispose()
$titleFont.Dispose(); $subtitleFont.Dispose(); $tableFont.Dispose(); $fieldFont.Dispose()
$fieldBoldFont.Dispose(); $relationFont.Dispose(); $legendFont.Dispose()
$textBrush.Dispose(); $mutedBrush.Dispose(); $headerBrush.Dispose(); $headerTextBrush.Dispose()
$tableBrush.Dispose(); $pkBrush.Dispose(); $fkBrush.Dispose(); $borderPen.Dispose(); $relationPen.Dispose()

Write-Output $outputPath
